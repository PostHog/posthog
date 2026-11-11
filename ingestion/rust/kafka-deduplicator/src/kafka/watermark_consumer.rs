use std::collections::{HashMap, HashSet};
use std::time::Duration;

use crate::kafka::batch_message::{Batch, BatchError, KafkaMessage};
use crate::kafka::error_handling;
use crate::kafka::metrics_consts::{
    WATERMARK_CONSUMER_KAFKA_ERROR, WATERMARK_CONSUMER_MESSAGES_RECEIVED,
    WATERMARK_CONSUMER_PARTITIONS_COMPLETED, WATERMARK_CONSUMER_UNEXPECTED_PARTITION,
};
use crate::kafka::types::{Partition, PartitionOffset};

use anyhow::{Context, Result};
use futures_util::StreamExt;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use serde::Deserialize;
use tokio::sync::mpsc;
use tokio::sync::oneshot::Receiver;
use tracing::{info, warn};

/// Low-level consumer that reads from assigned (topic, partition, offset) tuples
/// until each partition reaches its high-watermark, then shuts down.
/// No consumer group coordination; outputs batches via a channel.
///
/// Use `ConsumerConfigBuilder::for_watermark_consumer()` (or `Config::build_watermark_consumer_config()`)
/// to create an appropriate `ClientConfig` for this consumer.
pub struct WatermarkConsumer<T> {
    consumer: StreamConsumer,
    batch_size: usize,
    batch_timeout: Duration,
    batch_tx: mpsc::Sender<Batch<T>>,
    shutdown_rx: Receiver<()>,
    partition_targets: HashMap<Partition, i64>,
    completed_partitions: HashSet<Partition>,
}

impl<T> WatermarkConsumer<T>
where
    T: for<'de> Deserialize<'de>,
{
    /// Creates a watermark consumer and returns (consumer, batch_receiver).
    /// Caller runs `consumer.consume().await` to drive consumption; batches are received on the returned receiver.
    /// When all partitions reach high-watermark (or shutdown is signaled), the sender is dropped and the receiver sees channel close.
    pub fn new(
        config: &ClientConfig,
        assignments: Vec<PartitionOffset>,
        batch_size: usize,
        batch_timeout: Duration,
        fetch_watermarks_timeout: Duration,
        shutdown_rx: Receiver<()>,
    ) -> Result<(Self, mpsc::Receiver<Batch<T>>)> {
        if assignments.is_empty() {
            anyhow::bail!("assignments must not be empty");
        }

        let consumer: StreamConsumer =
            config.create().context("Failed to create Kafka consumer")?;

        let mut tpl = TopicPartitionList::new();
        for a in &assignments {
            tpl.add_partition_offset(a.topic(), a.partition_number(), Offset::Offset(a.offset()))
                .context("add_partition_offset")?;
        }
        consumer
            .assign(&tpl)
            .context("Failed to assign partitions")?;

        let mut partition_targets = HashMap::new();
        let mut completed_partitions = HashSet::new();

        for a in &assignments {
            let (_low, high) = consumer.fetch_watermarks(
                a.topic(),
                a.partition_number(),
                fetch_watermarks_timeout,
            )?;
            let partition = a.partition().clone();
            partition_targets.insert(partition.clone(), high);
            if high <= a.offset() {
                completed_partitions.insert(partition);
            }
        }

        let (batch_tx, batch_rx) = mpsc::channel(4);

        Ok((
            Self {
                consumer,
                batch_size,
                batch_timeout,
                batch_tx,
                shutdown_rx,
                partition_targets,
                completed_partitions,
            },
            batch_rx,
        ))
    }

    /// Drives consumption until all partitions reach high-watermark or shutdown.
    /// Drops the batch sender when done so the receiver sees channel close.
    pub async fn consume(mut self) -> Result<()> {
        info!(
            "Watermark consumer starting ({} partitions, {} already at watermark)",
            self.partition_targets.len(),
            self.completed_partitions.len()
        );

        let mut stream = self.consumer.stream();
        let batch_size = self.batch_size;
        let batch_timeout = self.batch_timeout;
        let mut kafka_error_count = 0u64;
        let mut stream_ended = false;

        loop {
            if self.completed_partitions.len() >= self.partition_targets.len() {
                info!("All partitions reached high-watermark, shutting down");
                break;
            }
            if stream_ended {
                break;
            }

            let mut batch = Batch::new_with_size_hint(batch_size);
            let batch_deadline = tokio::time::Instant::now() + batch_timeout;

            while batch.message_count() < batch_size {
                let now = tokio::time::Instant::now();
                if now >= batch_deadline {
                    break;
                }
                let remaining = batch_deadline.saturating_duration_since(now);

                tokio::select! {
                    _ = &mut self.shutdown_rx => {
                        info!("Shutdown signal received");
                        drop(self.batch_tx);
                        return Ok(());
                    }

                    next_msg = tokio::time::timeout(remaining, stream.next()) => {
                        match next_msg {
                            Ok(Some(Ok(borrowed_message))) => {
                                let partition = Partition::new(
                                    borrowed_message.topic().to_owned(),
                                    borrowed_message.partition(),
                                );
                                match KafkaMessage::<T>::from_borrowed_message(&borrowed_message) {
                                    Ok(kafka_message) => {
                                        kafka_error_count = 0;
                                        let offset = borrowed_message.offset();
                                        match self.partition_targets.get(&partition) {
                                            Some(&target) => {
                                                batch.push_message(kafka_message);
                                                if target > 0 && offset >= target - 1 {
                                                    self.completed_partitions.insert(partition);
                                                    metrics::counter!(WATERMARK_CONSUMER_PARTITIONS_COMPLETED)
                                                        .increment(1);
                                                }
                                            }
                                            None => {
                                                // Drop message from unassigned partition
                                                warn!(
                                                    partition = %partition,
                                                    offset = offset,
                                                    "Dropping message from unexpected partition not in assignment"
                                                );
                                                metrics::counter!(WATERMARK_CONSUMER_UNEXPECTED_PARTITION)
                                                    .increment(1);
                                            }
                                        }
                                    }
                                    Err(e) => {
                                        let wrapped_err = e.context("Error deserializing message");
                                        batch.push_error(BatchError::new(
                                            wrapped_err,
                                            Some(partition),
                                            Some(borrowed_message.offset()),
                                        ));
                                    }
                                }
                            }
                            Ok(Some(Err(e))) => {
                                kafka_error_count += 1;
                                if let Some(ke) =
                                    error_handling::handle_kafka_error(e, kafka_error_count, WATERMARK_CONSUMER_KAFKA_ERROR).await
                                {
                                    drop(self.batch_tx);
                                    return Err(ke.into());
                                }
                            }
                            Ok(None) => {
                                stream_ended = true;
                                break;
                            }
                            Err(_) => break,
                        }
                    }
                }
            }

            if !batch.is_empty() {
                let message_count = batch.message_count();
                metrics::counter!(WATERMARK_CONSUMER_MESSAGES_RECEIVED, "status" => "success")
                    .increment(message_count as u64);
                metrics::counter!(WATERMARK_CONSUMER_MESSAGES_RECEIVED, "status" => "error")
                    .increment(batch.error_count() as u64);
                if self.batch_tx.send(batch).await.is_err() {
                    warn!("Batch receiver dropped, stopping consumer");
                    return Ok(());
                }
            }
        }

        drop(self.batch_tx);
        Ok(())
    }
}

/// Returns true when a partition has no messages to read (high watermark at or before start offset).
#[cfg(test)]
pub(crate) fn partition_already_at_watermark(start_offset: i64, high_watermark: i64) -> bool {
    high_watermark <= start_offset
}

/// Returns true when the last message for this partition has been consumed (offset is at or past high - 1).
#[cfg(test)]
pub(crate) fn partition_done_after_message(offset: i64, high_watermark: i64) -> bool {
    high_watermark > 0 && offset >= high_watermark - 1
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_partition_already_at_watermark() {
        assert!(partition_already_at_watermark(0, 0));
        assert!(partition_already_at_watermark(5, 5));
        assert!(partition_already_at_watermark(10, 5));
        assert!(!partition_already_at_watermark(0, 1));
        assert!(!partition_already_at_watermark(4, 5));
    }

    #[test]
    fn test_partition_done_after_message() {
        // hwm == 0: never "done" regardless of offset (empty partition guard)
        assert!(!partition_done_after_message(0, 0));
        assert!(!partition_done_after_message(5, 0));

        // hwm == 1: only offset 0 (the single message) completes it
        assert!(partition_done_after_message(0, 1));

        // hwm == 2: offset must be >= 1
        assert!(!partition_done_after_message(0, 2));
        assert!(partition_done_after_message(1, 2));

        // offset past hwm-1 still counts as done
        assert!(partition_done_after_message(2, 2));

        // larger values: exact boundary and one short
        assert!(partition_done_after_message(99, 100));
        assert!(!partition_done_after_message(98, 100));
    }
}
