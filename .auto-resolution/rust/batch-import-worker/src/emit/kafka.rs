use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

use anyhow::Error;
use async_trait::async_trait;
use common_kafka::{
    kafka_producer::KafkaProduceError,
    transaction::{KafkaTransaction, TransactionalProducer},
};
use common_types::InternallyCapturedEvent;
use rdkafka::types::RDKafkaErrorCode;
use tracing::{error, info};

use crate::{context::AppContext, job::config::KafkaEmitterConfig};

use super::{Emitter, Transaction};

pub struct KafkaEmitter {
    producer: TransactionalProducer,
    topic: String,
    send_rate: u64, // Messages sent per second
}

pub struct KafkaEmitterTransaction<'a> {
    inner: KafkaTransaction<'a>,
    topic: &'a str,
    send_rate: u64,
    start: Instant,
    count: AtomicUsize,
}

impl KafkaEmitter {
    pub async fn new(
        emitter_config: KafkaEmitterConfig,
        transactional_id: &str, // Kafka transactional ID
        context: Arc<AppContext>,
    ) -> Result<Self, Error> {
        let producer = TransactionalProducer::from_config(
            &context.config.kafka,
            transactional_id,
            Duration::from_secs(emitter_config.transaction_timeout_seconds),
        )?;

        Ok(Self {
            producer,
            topic: emitter_config.topic,
            send_rate: emitter_config.send_rate,
        })
    }
}

#[async_trait]
impl Emitter for KafkaEmitter {
    async fn begin_write<'a>(&'a mut self) -> Result<Box<dyn Transaction<'a> + 'a>, Error> {
        let txn = self.producer.begin()?;
        Ok(Box::new(KafkaEmitterTransaction {
            inner: txn,
            start: Instant::now(),
            topic: &self.topic,
            send_rate: self.send_rate,
            count: AtomicUsize::new(0),
        }))
    }
}

#[async_trait]
impl<'a> Transaction<'a> for KafkaEmitterTransaction<'a> {
    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error> {
        for (idx, result) in self
            .inner
            .send_keyed_iter_to_kafka(self.topic, |e| Some(e.inner.key()), data.iter())
            .await
            .into_iter()
            .enumerate()
        {
            match result {
                Ok(_) => (),
                Err(KafkaProduceError::KafkaProduceError { error })
                    if matches!(
                        error.rdkafka_error_code(),
                        Some(RDKafkaErrorCode::MessageSizeTooLarge)
                    ) =>
                {
                    // We skip these aside from logging them, as there's not much we can do about them
                    error!("Message size too large: {:?}", data[idx].inner);
                }
                Err(err) => return Err(err.into()),
            }
        }

        self.count.fetch_add(data.len(), Ordering::SeqCst);

        Ok(())
    }

    async fn commit_write(self: Box<Self>) -> Result<Duration, Error> {
        let unboxed = *self;
        let count = unboxed.count.load(Ordering::SeqCst);
        let min_duration = unboxed.get_min_txn_duration(count);
        let txn_elapsed = unboxed.start.elapsed();
        let to_sleep = min_duration.saturating_sub(txn_elapsed);
        info!(
            "sent {} messages in {:?}, minimum send duration is {:?}, sleeping for {:?}",
            count, txn_elapsed, min_duration, to_sleep
        );
        unboxed.inner.commit()?;
        info!("committed transaction");
        Ok(to_sleep)
    }
}

impl<'a> KafkaEmitterTransaction<'a> {
    fn get_min_txn_duration(&self, txn_count: usize) -> Duration {
        // Get how long the send must take if this is the first send
        let max_send_rate = self.send_rate as f64;
        let batch_size = txn_count as f64;
        Duration::from_secs_f64(batch_size / max_send_rate)
    }
}
