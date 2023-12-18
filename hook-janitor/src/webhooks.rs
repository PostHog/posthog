use async_trait::async_trait;

use rdkafka::producer::FutureProducer;
use sqlx::postgres::{PgPool, PgPoolOptions};

use crate::cleanup::{Cleaner, CleanerError};
use crate::kafka_producer::KafkaContext;

#[allow(dead_code)]
pub struct WebhookCleaner {
    queue_name: String,
    table_name: String,
    pg_pool: PgPool,
    batch_size: u32,
    kafka_producer: FutureProducer<KafkaContext>,
    app_metrics_topic: String,
    plugin_log_entries_topic: String,
}

impl WebhookCleaner {
    pub fn new(
        queue_name: &str,
        table_name: &str,
        database_url: &str,
        batch_size: u32,
        kafka_producer: FutureProducer<KafkaContext>,
        app_metrics_topic: String,
        plugin_log_entries_topic: String,
    ) -> Result<Self, CleanerError> {
        let queue_name = queue_name.to_owned();
        let table_name = table_name.to_owned();
        let pg_pool = PgPoolOptions::new()
            .connect_lazy(database_url)
            .map_err(|error| CleanerError::PoolCreationError { error })?;

        Ok(Self {
            queue_name,
            table_name,
            pg_pool,
            batch_size,
            kafka_producer,
            app_metrics_topic,
            plugin_log_entries_topic,
        })
    }
}

#[async_trait]
impl Cleaner for WebhookCleaner {
    async fn cleanup(&self) {
        // TODO: collect stats on completed/failed rows
        // TODO: push metrics about those rows into `app_metrics`
        // TODO: delete those completed/failed rows
    }
}
