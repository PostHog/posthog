use std::time::Duration;

use kafka_deduplicator::kafka::{
    config::ConsumerConfigBuilder,
    types::{Partition, PartitionOffset},
    watermark_consumer::WatermarkConsumer,
};

use common_types::CapturedEvent;

use anyhow::Result;
use rdkafka::{
    admin::{AdminClient, AdminOptions, NewTopic, TopicReplication},
    config::ClientConfig,
    producer::{FutureProducer, FutureRecord},
    util::Timeout,
};
use time::OffsetDateTime;
use tokio::sync::oneshot;
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";
const TEST_TOPIC_BASE: &str = "kdedup-watermark-consumer-integration-test";

async fn create_topic_with_partitions(topic: &str, num_partitions: i32) -> Result<()> {
    use rdkafka::client::DefaultClientContext;

    let admin_client: AdminClient<DefaultClientContext> = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .create()?;

    let new_topic = NewTopic::new(topic, num_partitions, TopicReplication::Fixed(1));
    let opts = AdminOptions::new().operation_timeout(Some(Duration::from_secs(5)));

    let results = admin_client.create_topics(&[new_topic], &opts).await?;

    for result in results {
        match result {
            Ok(_) => {}
            Err((_, rdkafka::types::RDKafkaErrorCode::TopicAlreadyExists)) => {}
            Err((topic_name, err)) => {
                return Err(anyhow::anyhow!(
                    "Failed to create topic {topic_name}: {err:?}"
                ));
            }
        }
    }

    tokio::time::sleep(Duration::from_millis(500)).await;
    Ok(())
}

async fn send_test_messages_to_partition(
    topic: &str,
    partition: i32,
    messages: Vec<(String, String)>,
) -> Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    for (key, value) in messages {
        let record = FutureRecord::to(topic)
            .key(&key)
            .payload(&value)
            .partition(partition);

        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {e}"))?;
    }

    tokio::time::sleep(Duration::from_millis(100)).await;
    Ok(())
}

fn create_captured_event() -> CapturedEvent {
    let now = std::time::SystemTime::now();
    let now_offset_datetime = OffsetDateTime::from(now);
    let now_rfc3339 = chrono::DateTime::<chrono::Utc>::from(now).to_rfc3339();
    let distinct_id = Uuid::now_v7().to_string();
    let token = Uuid::now_v7().to_string();
    let event_name = "$pageview";
    let event_uuid = Uuid::now_v7();
    let data = format!(
        r#"{{"uuid": "{event_uuid}", "event": "{event_name}", "distinct_id": "{distinct_id}", "token": "{token}", "properties": {{}}}}"#,
    );

    CapturedEvent {
        uuid: event_uuid,
        distinct_id: distinct_id.to_string(),
        session_id: None,
        ip: "127.0.0.1".to_string(),
        now: now_rfc3339.clone(),
        token: token.to_string(),
        data: data.to_string(),
        sent_at: Some(now_offset_datetime),
        event: event_name.to_string(),
        timestamp: chrono::Utc::now(),
        is_cookieless_mode: false,
        historical_migration: false,
    }
}

fn generate_test_messages(count: usize) -> Vec<(String, String)> {
    (0..count)
        .map(|i| {
            let payload = create_captured_event();
            let serialized = serde_json::to_string(&payload).unwrap();
            (format!("key_{i}"), serialized)
        })
        .collect()
}

/// Watermark consumer reads from assigned (topic, partition, offset) until each partition
/// reaches high-watermark, then closes the batch channel. Verifies we receive exactly
/// the expected messages and then the channel closes.
#[tokio::test]
async fn test_watermark_consumer_reads_to_high_watermark_then_closes() -> Result<()> {
    let test_topic = format!("{}-{}", TEST_TOPIC_BASE, Uuid::now_v7());
    let messages_per_partition = 20;
    let partitions_to_use = vec![0, 1, 2];
    let total_messages = messages_per_partition * partitions_to_use.len();

    create_topic_with_partitions(&test_topic, partitions_to_use.len() as i32).await?;

    for partition in &partitions_to_use {
        let messages = generate_test_messages(messages_per_partition);
        send_test_messages_to_partition(&test_topic, *partition, messages).await?;
    }

    let group_id = format!("watermark-consumer-{}", Uuid::now_v7());
    let config = ConsumerConfigBuilder::for_watermark_consumer(KAFKA_BROKERS, &group_id).build();

    let assignments: Vec<PartitionOffset> = partitions_to_use
        .iter()
        .map(|&p| PartitionOffset::new(Partition::new(test_topic.clone(), p), 0))
        .collect();

    let (shutdown_tx, shutdown_rx) = oneshot::channel();

    let (consumer, mut batch_rx) = WatermarkConsumer::<CapturedEvent>::new(
        &config,
        assignments,
        50,
        Duration::from_millis(200),
        Duration::from_secs(5),
        shutdown_rx,
    )?;

    let consumer_handle = tokio::spawn(async move { consumer.consume().await });

    let mut total_received = 0usize;
    while let Some(batch) = batch_rx.recv().await {
        let (msgs, errs) = batch.unpack();
        if !errs.is_empty() {
            panic!("Errors in batch: {errs:?}");
        }
        total_received += msgs.len();
    }

    assert_eq!(
        total_received, total_messages,
        "Expected {} messages, got {}",
        total_messages, total_received
    );

    let consume_result = tokio::time::timeout(Duration::from_secs(10), consumer_handle).await;
    assert!(consume_result.is_ok(), "Consumer task should complete");
    let join_result = consume_result.unwrap();
    assert!(join_result.is_ok(), "Consumer should not panic");
    join_result.unwrap()?;

    drop(shutdown_tx);
    Ok(())
}
