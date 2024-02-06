use std::time::Duration;

use async_trait::async_trait;
use metrics::{counter, gauge, histogram};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::producer::{DeliveryFuture, FutureProducer, FutureRecord, Producer};
use rdkafka::util::Timeout;
use rdkafka::ClientConfig;
use tokio::task::JoinSet;
use tracing::log::{debug, error, info};
use tracing::{info_span, instrument, Instrument};

use crate::api::CaptureError;
use crate::config::KafkaConfig;
use crate::event::ProcessedEvent;
use crate::health::HealthHandle;
use crate::limiters::overflow::OverflowLimiter;
use crate::prometheus::report_dropped_events;
use crate::sinks::Event;

struct KafkaContext {
    liveness: HealthHandle,
}

impl rdkafka::ClientContext for KafkaContext {
    fn stats(&self, stats: rdkafka::Statistics) {
        // Signal liveness, as the main rdkafka loop is running and calling us
        self.liveness.report_healthy_blocking();

        // Update exported metrics
        gauge!("capture_kafka_callback_queue_depth",).set(stats.replyq as f64);
        gauge!("capture_kafka_producer_queue_depth",).set(stats.msg_cnt as f64);
        gauge!("capture_kafka_producer_queue_depth_limit",).set(stats.msg_max as f64);
        gauge!("capture_kafka_producer_queue_bytes",).set(stats.msg_max as f64);
        gauge!("capture_kafka_producer_queue_bytes_limit",).set(stats.msg_size_max as f64);

        for (topic, stats) in stats.topics {
            gauge!(
                "capture_kafka_produce_avg_batch_size_bytes",
                               "topic" => topic.clone()
            )
            .set(stats.batchsize.avg as f64);
            gauge!(
                "capture_kafka_produce_avg_batch_size_events",

                "topic" => topic
            )
            .set(stats.batchcnt.avg as f64);
        }

        for (_, stats) in stats.brokers {
            let id_string = format!("{}", stats.nodeid);
            gauge!(
                "capture_kafka_broker_requests_pending",

                "broker" => id_string.clone()
            )
            .set(stats.outbuf_cnt as f64);
            gauge!(
                "capture_kafka_broker_responses_awaiting",

                "broker" => id_string.clone()
            )
            .set(stats.waitresp_cnt as f64);
            counter!(
                "capture_kafka_broker_tx_errors_total",

                "broker" => id_string.clone()
            )
            .absolute(stats.txerrs);
            counter!(
                "capture_kafka_broker_rx_errors_total",

                "broker" => id_string
            )
            .absolute(stats.rxerrs);
        }
    }
}

#[derive(Clone)]
pub struct KafkaSink {
    producer: FutureProducer<KafkaContext>,
    topic: String,
    partition: OverflowLimiter,
}

impl KafkaSink {
    pub fn new(
        config: KafkaConfig,
        liveness: HealthHandle,
        partition: OverflowLimiter,
    ) -> anyhow::Result<KafkaSink> {
        info!("connecting to Kafka brokers at {}...", config.kafka_hosts);

        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("linger.ms", config.kafka_producer_linger_ms.to_string())
            .set(
                "message.timeout.ms",
                config.kafka_message_timeout_ms.to_string(),
            )
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

    pub fn flush(&self) -> Result<(), KafkaError> {
        // TODO: hook it up on shutdown
        self.producer.flush(Duration::new(30, 0))
    }

    async fn kafka_send(
        producer: FutureProducer<KafkaContext>,
        topic: String,
        event: ProcessedEvent,
        limited: bool,
    ) -> Result<DeliveryFuture, CaptureError> {
        let payload = serde_json::to_string(&event).map_err(|e| {
            error!("failed to serialize event: {}", e);
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
            Ok(ack) => Ok(ack),
            Err((e, _)) => match e.rdkafka_error_code() {
                Some(RDKafkaErrorCode::MessageSizeTooLarge) => {
                    report_dropped_events("kafka_message_size", 1);
                    Err(CaptureError::EventTooBig)
                }
                _ => {
                    // TODO(maybe someday): Don't drop them but write them somewhere and try again
                    report_dropped_events("kafka_write_error", 1);
                    error!("failed to produce event: {}", e);
                    Err(CaptureError::RetryableSinkError)
                }
            },
        }
    }

    async fn process_ack(delivery: DeliveryFuture) -> Result<(), CaptureError> {
        match delivery.await {
            Err(_) => {
                // Cancelled due to timeout while retrying
                counter!("capture_kafka_produce_errors_total").increment(1);
                error!("failed to produce to Kafka before write timeout");
                Err(CaptureError::RetryableSinkError)
            }
            Ok(Err((KafkaError::MessageProduction(RDKafkaErrorCode::MessageSizeTooLarge), _))) => {
                // Rejected by broker due to message size
                report_dropped_events("kafka_message_size", 1);
                Err(CaptureError::EventTooBig)
            }
            Ok(Err((err, _))) => {
                // Unretriable produce error
                counter!("capture_kafka_produce_errors_total").increment(1);
                error!("failed to produce to Kafka: {}", err);
                Err(CaptureError::RetryableSinkError)
            }
            Ok(Ok(_)) => {
                counter!("capture_events_ingested_total").increment(1);
                Ok(())
            }
        }
    }
}

#[async_trait]
impl Event for KafkaSink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let limited = self.partition.is_limited(&event.key());
        let ack =
            Self::kafka_send(self.producer.clone(), self.topic.clone(), event, limited).await?;
        histogram!("capture_event_batch_size").record(1.0);
        Self::process_ack(ack)
            .instrument(info_span!("ack_wait_one"))
            .await
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let mut set = JoinSet::new();
        let batch_size = events.len();
        for event in events {
            let producer = self.producer.clone();
            let topic = self.topic.clone();
            let limited = self.partition.is_limited(&event.key());

            // We await kafka_send to get events in the producer queue sequentially
            let ack = Self::kafka_send(producer, topic, event, limited).await?;

            // Then stash the returned DeliveryFuture, waiting concurrently for the write ACKs from brokers.
            set.spawn(Self::process_ack(ack));
        }

        // Await on all the produce promises, fail batch on first failure
        async move {
            while let Some(res) = set.join_next().await {
                match res {
                    Ok(Ok(_)) => {}
                    Ok(Err(err)) => {
                        set.abort_all();
                        return Err(err);
                    }
                    Err(err) => {
                        set.abort_all();
                        error!("join error while waiting on Kafka ACK: {:?}", err);
                        return Err(CaptureError::RetryableSinkError);
                    }
                }
            }
            Ok(())
        }
        .instrument(info_span!("ack_wait_many"))
        .await?;

        histogram!("capture_event_batch_size").record(batch_size as f64);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use crate::api::CaptureError;
    use crate::config;
    use crate::event::ProcessedEvent;
    use crate::health::HealthRegistry;
    use crate::limiters::overflow::OverflowLimiter;
    use crate::sinks::kafka::KafkaSink;
    use crate::sinks::Event;
    use crate::utils::uuid_v7;
    use rand::distributions::Alphanumeric;
    use rand::Rng;
    use rdkafka::mocking::MockCluster;
    use rdkafka::producer::DefaultProducerContext;
    use rdkafka::types::{RDKafkaApiKey, RDKafkaRespErr};
    use std::num::NonZeroU32;
    use time::Duration;

    async fn start_on_mocked_sink() -> (MockCluster<'static, DefaultProducerContext>, KafkaSink) {
        let registry = HealthRegistry::new("liveness");
        let handle = registry
            .register("one".to_string(), Duration::seconds(30))
            .await;
        let limiter = OverflowLimiter::new(
            NonZeroU32::new(10).unwrap(),
            NonZeroU32::new(10).unwrap(),
            None,
        );
        let cluster = MockCluster::new(1).expect("failed to create mock brokers");
        let config = config::KafkaConfig {
            kafka_producer_linger_ms: 0,
            kafka_producer_queue_mib: 50,
            kafka_message_timeout_ms: 500,
            kafka_compression_codec: "none".to_string(),
            kafka_hosts: cluster.bootstrap_servers(),
            kafka_topic: "events_plugin_ingestion".to_string(),
            kafka_tls: false,
        };
        let sink = KafkaSink::new(config, handle, limiter).expect("failed to create sink");
        (cluster, sink)
    }

    #[tokio::test]
    async fn kafka_sink_error_handling() {
        // Uses a mocked Kafka broker that allows injecting write errors, to check error handling.
        // We test different cases in a single test to amortize the startup cost of the producer.

        let (cluster, sink) = start_on_mocked_sink().await;
        let event: ProcessedEvent = ProcessedEvent {
            uuid: uuid_v7(),
            distinct_id: "id1".to_string(),
            ip: "".to_string(),
            data: "".to_string(),
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
        };

        // Wait for producer to be healthy, to keep kafka_message_timeout_ms short and tests faster
        for _ in 0..20 {
            if sink.send(event.clone()).await.is_ok() {
                break;
            }
        }

        // Send events to confirm happy path
        sink.send(event.clone())
            .await
            .expect("failed to send one initial event");
        sink.send_batch(vec![event.clone(), event.clone()])
            .await
            .expect("failed to send initial event batch");

        // Producer should reject a 2MB message, twice the default `message.max.bytes`
        let big_data = rand::thread_rng()
            .sample_iter(Alphanumeric)
            .take(2_000_000)
            .map(char::from)
            .collect();
        let big_event: ProcessedEvent = ProcessedEvent {
            uuid: uuid_v7(),
            distinct_id: "id1".to_string(),
            ip: "".to_string(),
            data: big_data,
            now: "".to_string(),
            sent_at: None,
            token: "token1".to_string(),
        };
        match sink.send(big_event).await {
            Err(CaptureError::EventTooBig) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };

        // Simulate unretriable errors
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_MSG_SIZE_TOO_LARGE; 1];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send(event.clone()).await {
            Err(CaptureError::EventTooBig) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_INVALID_PARTITIONS; 1];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send_batch(vec![event.clone(), event.clone()]).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };

        // Simulate transient errors, messages should go through OK
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 2];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        sink.send(event.clone())
            .await
            .expect("failed to send one event after recovery");
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 2];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        sink.send_batch(vec![event.clone(), event.clone()])
            .await
            .expect("failed to send event batch after recovery");

        // Timeout on a sustained transient error
        cluster.clear_request_errors(RDKafkaApiKey::Produce);
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_BROKER_NOT_AVAILABLE; 50];
        cluster.request_errors(RDKafkaApiKey::Produce, &err);
        match sink.send(event.clone()).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };
        match sink.send_batch(vec![event.clone(), event.clone()]).await {
            Err(CaptureError::RetryableSinkError) => {} // Expected
            Err(err) => panic!("wrong error code {}", err),
            Ok(()) => panic!("should have errored"),
        };
    }
}
