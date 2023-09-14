use async_trait::async_trait;
use tokio::task::JoinSet;

use crate::api::CaptureError;
use rdkafka::config::ClientConfig;
use rdkafka::error::RDKafkaErrorCode;
use rdkafka::producer::future_producer::{FutureProducer, FutureRecord};

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

        metrics::increment_counter!("capture_events_total");

        Ok(())
    }
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let span = tracing::span!(tracing::Level::INFO, "batch of events");
        let _enter = span.enter();

        for event in events {
            metrics::increment_counter!("capture_events_total");
            tracing::info!("event: {:?}", event);
        }

        Ok(())
    }
}

#[derive(Clone)]
pub struct KafkaSink {
    producer: FutureProducer,
    topic: String,
}

impl KafkaSink {
    pub fn new(topic: String, brokers: String) -> anyhow::Result<KafkaSink> {
        let producer: FutureProducer = ClientConfig::new()
            .set("bootstrap.servers", &brokers)
            .create()?;

        Ok(KafkaSink { producer, topic })
    }
}

impl KafkaSink {
    async fn kafka_send(
        producer: FutureProducer,
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

        while let Some(res) = set.join_next().await {
            println!("{:?}", res);
        }

        Ok(())
    }
}
