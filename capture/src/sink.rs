use std::time::Duration;

use async_trait::async_trait;
use metrics::{absolute_counter, counter, gauge, histogram};
use rdkafka::config::ClientConfig;
use rdkafka::error::RDKafkaErrorCode;
use rdkafka::producer::future_producer::{FutureProducer, FutureRecord};
use rdkafka::producer::Producer;
use rdkafka::util::Timeout;
use tokio::task::JoinSet;
use tracing::{debug, info, instrument};

use crate::api::CaptureError;
use crate::config::KafkaConfig;
use crate::event::ProcessedEvent;
use crate::health::HealthHandle;
use crate::partition_limits::PartitionLimiter;
use crate::prometheus::report_dropped_events;

#[async_trait]
pub trait EventSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError>;
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}

pub struct PrintSink {}

#[async_trait]
impl EventSink for PrintSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        info!("single event: {:?}", event);
        counter!("capture_events_ingested_total", 1);

        Ok(())
    }
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let span = tracing::span!(tracing::Level::INFO, "batch of events");
        let _enter = span.enter();

        histogram!("capture_event_batch_size", events.len() as f64);
        counter!("capture_events_ingested_total", events.len() as u64);
        for event in events {
            info!("event: {:?}", event);
        }

        Ok(())
    }
}

struct KafkaContext {
    liveness: HealthHandle,
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, stats: rdkafka::Statistics) {
        // Signal liveness, as the main rdkafka loop is running and calling us
        self.liveness.report_healthy_blocking();

        // Update exported metrics
        gauge!("capture_kafka_callback_queue_depth", stats.replyq as f64);
        gauge!("capture_kafka_producer_queue_depth", stats.msg_cnt as f64);
        gauge!(
            "capture_kafka_producer_queue_depth_limit",
            stats.msg_max as f64
        );
        gauge!("capture_kafka_producer_queue_bytes", stats.msg_max as f64);
        gauge!(
            "capture_kafka_producer_queue_bytes_limit",
            stats.msg_size_max as f64
        );

        for (topic, stats) in stats.topics {
            gauge!(
                "capture_kafka_produce_avg_batch_size_bytes",
                stats.batchsize.avg as f64,
                "topic" => topic.clone()
            );
            gauge!(
                "capture_kafka_produce_avg_batch_size_events",
                stats.batchcnt.avg as f64,
                "topic" => topic
            );
        }

        for (_, stats) in stats.brokers {
            let id_string = format!("{}", stats.nodeid);
            gauge!(
                "capture_kafka_broker_requests_pending",
                stats.outbuf_cnt as f64,
                "broker" => id_string.clone()
            );
            gauge!(
                "capture_kafka_broker_responses_awaiting",
                stats.waitresp_cnt as f64,
                "broker" => id_string.clone()
            );
            absolute_counter!(
                "capture_kafka_broker_tx_errors_total",
                stats.txerrs,
                "broker" => id_string.clone()
            );
            absolute_counter!(
                "capture_kafka_broker_rx_errors_total",
                stats.rxerrs,
                "broker" => id_string
            );
        }
    }
}

#[derive(Clone)]
pub struct KafkaSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
    partition: PartitionLimiter,
}

impl KafkaSink {
    pub fn new(
        config: KafkaConfig,
        liveness: HealthHandle,
        partition: PartitionLimiter,
    ) -> anyhow::Result<KafkaSink> {
        info!("connecting to Kafka brokers at {}...", config.kafka_hosts);

        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("linger.ms", config.kafka_producer_linger_ms.to_string())
            .set("compression.codec", config.kafka_compression_codec)
            .set(
                "queue.buffering.max.kbytes",
                (config.kafka_producer_queue_mib * 1024).to_string(),
            );

        if config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        debug!("rdkafka configuration: {:?}", client_config);
        let producer: FutureProducer<KafkaContext> =
            client_config.create_with_context(KafkaContext { liveness })?;

        // Ping the cluster to make sure we can reach brokers, fail after 10 seconds
        _ = producer.client().fetch_metadata(
            Some("__consumer_offsets"),
            Timeout::After(Duration::new(10, 0)),
        )?;
        info!("connected to Kafka brokers");

        Ok(KafkaSink {
            producer,
            partition,
            topic: config.kafka_topic,
        })
    }
}

impl KafkaSink {
    async fn kafka_send(
        producer: FutureProducer<KafkaContext>,
        topic: String,
        event: ProcessedEvent,
        limited: bool,
    ) -> Result<(), CaptureError> {
        let payload = serde_json::to_string(&event).map_err(|e| {
            tracing::error!("failed to serialize event: {}", e);
            CaptureError::NonRetryableSinkError
        })?;

        let key = event.key();
        let partition_key = if limited { None } else { Some(key.as_str()) };

        match producer.send_result(FutureRecord {
            topic: topic.as_str(),
            payload: Some(&payload),
            partition: None,
            key: partition_key,
            timestamp: None,
            headers: None,
        }) {
            Ok(_) => Ok(()),
            Err((e, _)) => match e.rdkafka_error_code() {
                Some(RDKafkaErrorCode::InvalidMessageSize) => {
                    report_dropped_events("kafka_message_size", 1);
                    Err(CaptureError::EventTooBig)
                }
                _ => {
                    // TODO(maybe someday): Don't drop them but write them somewhere and try again
                    report_dropped_events("kafka_write_error", 1);
                    tracing::error!("failed to produce event: {}", e);
                    Err(CaptureError::RetryableSinkError)
                }
            },
        }
    }
}

#[async_trait]
impl EventSink for KafkaSink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let limited = self.partition.is_limited(&event.key());
        Self::kafka_send(self.producer.clone(), self.topic.clone(), event, limited).await?;

        histogram!("capture_event_batch_size", 1.0);
        counter!("capture_events_ingested_total", 1);

        Ok(())
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let mut set = JoinSet::new();
        let batch_size = events.len();
        for event in events {
            let producer = self.producer.clone();
            let topic = self.topic.clone();

            let limited = self.partition.is_limited(&event.key());
            set.spawn(Self::kafka_send(producer, topic, event, limited));
        }

        // Await on all the produce promises
        while (set.join_next().await).is_some() {}

        histogram!("capture_event_batch_size", batch_size as f64);
        counter!("capture_events_ingested_total", batch_size as u64);
        Ok(())
    }
}
