use async_trait::async_trait;
use metrics::{absolute_counter, counter, gauge, histogram};
use std::time::Duration;
use tokio::task::JoinSet;

use crate::api::CaptureError;
use rdkafka::config::{ClientConfig, FromClientConfigAndContext};
use rdkafka::error::RDKafkaErrorCode;
use rdkafka::producer::future_producer::{FutureProducer, FutureRecord};
use rdkafka::producer::Producer;
use rdkafka::util::Timeout;
use tracing::info;

use crate::event::ProcessedEvent;

#[async_trait]
pub trait EventSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError>;
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError>;
}

pub struct PrintSink {}

#[async_trait]
impl EventSink for PrintSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        tracing::info!("single event: {:?}", event);
        counter!("capture_events_ingested_total", 1);

        Ok(())
    }
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let span = tracing::span!(tracing::Level::INFO, "batch of events");
        let _enter = span.enter();

        histogram!("capture_event_batch_size", events.len() as f64);
        counter!("capture_events_ingested_total", events.len() as u64);
        for event in events {
            tracing::info!("event: {:?}", event);
        }

        Ok(())
    }
}

struct KafkaContext;

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, stats: rdkafka::Statistics) {
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
}

impl KafkaSink {
    pub fn new(topic: String, brokers: String, tls: bool) -> anyhow::Result<KafkaSink> {
        info!("connecting to Kafka brokers at {}...", brokers);
        let mut config = ClientConfig::new();
        config
            .set("bootstrap.servers", &brokers)
            .set("statistics.interval.ms", "10000");

        if tls {
            config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        let producer = FutureProducer::from_config_and_context(&config, KafkaContext)?;

        // Ping the cluster to make sure we can reach brokers
        _ = producer.client().fetch_metadata(
            Some("__consumer_offsets"),
            Timeout::After(Duration::new(10, 0)),
        )?;
        info!("connected to Kafka brokers");

        Ok(KafkaSink { producer, topic })
    }
}

impl KafkaSink {
    async fn kafka_send(
        producer: FutureProducer<KafkaContext>,
        topic: String,
        event: ProcessedEvent,
    ) -> Result<(), CaptureError> {
        let payload = serde_json::to_string(&event).map_err(|e| {
            tracing::error!("failed to serialize event: {}", e);
            CaptureError::NonRetryableSinkError
        })?;

        let key = event.key();

        match producer.send_result(FutureRecord {
            topic: topic.as_str(),
            payload: Some(&payload),
            partition: None,
            key: Some(&key),
            timestamp: None,
            headers: None,
        }) {
            Ok(_) => {
                metrics::increment_counter!("capture_events_ingested");
                Ok(())
            }
            Err((e, _)) => match e.rdkafka_error_code() {
                Some(RDKafkaErrorCode::InvalidMessageSize) => {
                    metrics::increment_counter!("capture_events_dropped_too_big");
                    Err(CaptureError::EventTooBig)
                }
                _ => {
                    // TODO(maybe someday): Don't drop them but write them somewhere and try again
                    metrics::increment_counter!("capture_events_dropped");
                    tracing::error!("failed to produce event: {}", e);
                    Err(CaptureError::RetryableSinkError)
                }
            },
        }
    }
}

#[async_trait]
impl EventSink for KafkaSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        Self::kafka_send(self.producer.clone(), self.topic.clone(), event).await
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let mut set = JoinSet::new();

        for event in events {
            let producer = self.producer.clone();
            let topic = self.topic.clone();

            set.spawn(Self::kafka_send(producer, topic, event));
        }

        // Await on all the produce promises
        while (set.join_next().await).is_some() {}

        Ok(())
    }
}
