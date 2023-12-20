use std::time::Duration;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use futures::future::join_all;
use hook_common::webhook::WebhookJobError;
use rdkafka::error::KafkaError;
use rdkafka::producer::{FutureProducer, FutureRecord};
use serde_json::error::Error as SerdeError;
use sqlx::postgres::{PgPool, PgPoolOptions, Postgres};
use sqlx::types::{chrono, Uuid};
use sqlx::Transaction;
use thiserror::Error;
use tracing::{debug, error};

use crate::cleanup::Cleaner;
use crate::kafka_producer::KafkaContext;

use hook_common::kafka_messages::app_metrics::{AppMetric, AppMetricCategory};

#[derive(Error, Debug)]
pub enum WebhookCleanerError {
    #[error("failed to create postgres pool: {error}")]
    PoolCreationError { error: sqlx::Error },
    #[error("failed to acquire conn and start txn: {error}")]
    StartTxnError { error: sqlx::Error },
    #[error("failed to get completed rows: {error}")]
    GetCompletedRowsError { error: sqlx::Error },
    #[error("failed to get failed rows: {error}")]
    GetFailedRowsError { error: sqlx::Error },
    #[error("failed to serialize rows: {error}")]
    SerializeRowsError { error: SerdeError },
    #[error("failed to produce to kafka: {error}")]
    KafkaProduceError { error: KafkaError },
    #[error("failed to produce to kafka (timeout)")]
    KafkaProduceCanceled,
    #[error("failed to delete rows: {error}")]
    DeleteRowsError { error: sqlx::Error },
    #[error("failed to commit txn: {error}")]
    CommitTxnError { error: sqlx::Error },
}

type Result<T, E = WebhookCleanerError> = std::result::Result<T, E>;

pub struct WebhookCleaner {
    queue_name: String,
    table_name: String,
    pg_pool: PgPool,
    kafka_producer: FutureProducer<KafkaContext>,
    app_metrics_topic: String,
}

#[derive(sqlx::FromRow, Debug)]
struct CompletedRow {
    // App Metrics truncates/aggregates rows on the hour, so we take advantage of that to GROUP BY
    // and aggregate to select fewer rows.
    hour: DateTime<Utc>,
    // A note about the `try_from`s: Postgres returns all of those types as `bigint` (i64), but
    // we know their true sizes, and so we can convert them to the correct types here. If this
    // ever fails then something has gone wrong.
    #[sqlx(try_from = "i64")]
    team_id: u32,
    #[sqlx(try_from = "i64")]
    plugin_config_id: u32,
    #[sqlx(try_from = "i64")]
    successes: u32,
}

#[derive(sqlx::FromRow, Debug)]
struct FailedRow {
    // App Metrics truncates/aggregates rows on the hour, so we take advantage of that to GROUP BY
    // and aggregate to select fewer rows.
    hour: DateTime<Utc>,
    // A note about the `try_from`s: Postgres returns all of those types as `bigint` (i64), but
    // we know their true sizes, and so we can convert them to the correct types here. If this
    // ever fails then something has gone wrong.
    #[sqlx(try_from = "i64")]
    team_id: u32,
    #[sqlx(try_from = "i64")]
    plugin_config_id: u32,
    #[sqlx(json)]
    last_error: WebhookJobError,
    #[sqlx(try_from = "i64")]
    failures: u32,
}

// A simple wrapper type that ensures we don't use any old Transaction object when we need one
// that has set the isolation level to serializable.
struct SerializableTxn<'a>(Transaction<'a, Postgres>);

impl WebhookCleaner {
    pub fn new(
        queue_name: &str,
        table_name: &str,
        database_url: &str,
        kafka_producer: FutureProducer<KafkaContext>,
        app_metrics_topic: String,
    ) -> Result<Self> {
        let queue_name = queue_name.to_owned();
        let table_name = table_name.to_owned();
        let pg_pool = PgPoolOptions::new()
            .acquire_timeout(Duration::from_secs(10))
            .connect_lazy(database_url)
            .map_err(|error| WebhookCleanerError::PoolCreationError { error })?;

        Ok(Self {
            queue_name,
            table_name,
            pg_pool,
            kafka_producer,
            app_metrics_topic,
        })
    }

    #[allow(dead_code)] // This is used in tests.
    pub fn new_from_pool(
        queue_name: &str,
        table_name: &str,
        pg_pool: PgPool,
        kafka_producer: FutureProducer<KafkaContext>,
        app_metrics_topic: String,
    ) -> Result<Self> {
        let queue_name = queue_name.to_owned();
        let table_name = table_name.to_owned();

        Ok(Self {
            queue_name,
            table_name,
            pg_pool,
            kafka_producer,
            app_metrics_topic,
        })
    }

    async fn start_serializable_txn(&self) -> Result<SerializableTxn> {
        let mut tx = self
            .pg_pool
            .begin()
            .await
            .map_err(|e| WebhookCleanerError::StartTxnError { error: e })?;

        // We use serializable isolation so that we observe a snapshot of the DB at the time we
        // start the cleanup process. This prevents us from accidentally deleting rows that are
        // added (or become 'completed' or 'failed') after we start the cleanup process.
        //
        // If we find that this has a significant performance impact, we could instead move
        // rows to a temporary table for processing and then deletion.
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(|e| WebhookCleanerError::StartTxnError { error: e })?;

        Ok(SerializableTxn(tx))
    }

    async fn get_completed_rows(&self, tx: &mut SerializableTxn<'_>) -> Result<Vec<CompletedRow>> {
        let base_query = format!(
            r#"
            SELECT DATE_TRUNC('hour', finished_at) AS hour,
                (metadata->>'team_id')::bigint AS team_id,
                (metadata->>'plugin_config_id')::bigint AS plugin_config_id,
                count(*) as successes
            FROM {0}
            WHERE status = 'completed'
              AND queue = $1
            GROUP BY hour, team_id, plugin_config_id
            ORDER BY hour, team_id, plugin_config_id;
            "#,
            self.table_name
        );

        let rows = sqlx::query_as::<_, CompletedRow>(&base_query)
            .bind(&self.queue_name)
            .fetch_all(&mut *tx.0)
            .await
            .map_err(|e| WebhookCleanerError::GetCompletedRowsError { error: e })?;

        Ok(rows)
    }

    fn serialize_completed_rows(&self, completed_rows: Vec<CompletedRow>) -> Result<Vec<String>> {
        let mut payloads = Vec::new();

        for row in completed_rows {
            let app_metric = AppMetric {
                timestamp: row.hour,
                team_id: row.team_id,
                plugin_config_id: row.plugin_config_id,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: row.successes,
                successes_on_retry: 0,
                failures: 0,
                error_uuid: None,
                error_type: None,
                error_details: None,
            };

            let payload = serde_json::to_string(&app_metric)
                .map_err(|e| WebhookCleanerError::SerializeRowsError { error: e })?;

            payloads.push(payload)
        }

        Ok(payloads)
    }

    async fn get_failed_rows(&self, tx: &mut SerializableTxn<'_>) -> Result<Vec<FailedRow>> {
        let base_query = format!(
            r#"
            SELECT DATE_TRUNC('hour', finished_at) AS hour,
                   (metadata->>'team_id')::bigint AS team_id,
                   (metadata->>'plugin_config_id')::bigint AS plugin_config_id,
                   errors[array_upper(errors, 1)] AS last_error,
                   count(*) as failures
            FROM {0}
            WHERE status = 'failed'
              AND queue = $1
            GROUP BY hour, team_id, plugin_config_id, last_error
            ORDER BY hour, team_id, plugin_config_id, last_error;
            "#,
            self.table_name
        );

        let rows = sqlx::query_as::<_, FailedRow>(&base_query)
            .bind(&self.queue_name)
            .fetch_all(&mut *tx.0)
            .await
            .map_err(|e| WebhookCleanerError::GetFailedRowsError { error: e })?;

        Ok(rows)
    }

    fn serialize_failed_rows(&self, failed_rows: Vec<FailedRow>) -> Result<Vec<String>> {
        let mut payloads = Vec::new();

        for row in failed_rows {
            let app_metric = AppMetric {
                timestamp: row.hour,
                team_id: row.team_id,
                plugin_config_id: row.plugin_config_id,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 0,
                successes_on_retry: 0,
                failures: row.failures,
                error_uuid: Some(Uuid::now_v7()),
                error_type: Some(row.last_error.r#type),
                error_details: Some(row.last_error.details),
            };

            let payload = serde_json::to_string(&app_metric)
                .map_err(|e| WebhookCleanerError::SerializeRowsError { error: e })?;

            payloads.push(payload)
        }

        Ok(payloads)
    }

    async fn send_messages_to_kafka(&self, payloads: Vec<String>) -> Result<()> {
        let mut delivery_futures = Vec::new();

        for payload in payloads {
            match self.kafka_producer.send_result(FutureRecord {
                topic: self.app_metrics_topic.as_str(),
                payload: Some(&payload),
                partition: None,
                key: None::<&str>,
                timestamp: None,
                headers: None,
            }) {
                Ok(future) => delivery_futures.push(future),
                Err((error, _)) => return Err(WebhookCleanerError::KafkaProduceError { error }),
            }
        }

        for result in join_all(delivery_futures).await {
            match result {
                Ok(Ok(_)) => {}
                Ok(Err((error, _))) => {
                    return Err(WebhookCleanerError::KafkaProduceError { error })
                }
                Err(_) => {
                    // Cancelled due to timeout while retrying
                    return Err(WebhookCleanerError::KafkaProduceCanceled);
                }
            }
        }

        Ok(())
    }

    async fn delete_observed_rows(&self, tx: &mut SerializableTxn<'_>) -> Result<u64> {
        // This DELETE is only safe because we are in serializable isolation mode, see the note
        // in `start_serializable_txn`.
        let base_query = format!(
            r#"
            DELETE FROM {0}
            WHERE status IN ('failed', 'completed')
              AND queue = $1;
            "#,
            self.table_name
        );

        let result = sqlx::query(&base_query)
            .bind(&self.queue_name)
            .execute(&mut *tx.0)
            .await
            .map_err(|e| WebhookCleanerError::DeleteRowsError { error: e })?;

        Ok(result.rows_affected())
    }

    async fn commit_txn(&self, tx: SerializableTxn<'_>) -> Result<()> {
        tx.0.commit()
            .await
            .map_err(|e| WebhookCleanerError::CommitTxnError { error: e })?;

        Ok(())
    }

    async fn cleanup_impl(&self) -> Result<()> {
        debug!("WebhookCleaner starting cleanup");

        // Note that we select all completed and failed rows without any pagination at the moment.
        // We aggregrate as much as possible with GROUP BY, truncating the timestamp down to the
        // hour just like App Metrics does. A completed row is 24 bytes (and aggregates an entire
        // hour per `plugin_config_id`), and a failed row is 104 bytes + the error message length
        // (and aggregates an entire hour per `plugin_config_id` per `error`), so we can fit a lot
        // of rows in memory. It seems unlikely we'll need to paginate, but that can be added in the
        // future if necessary.

        let mut tx = self.start_serializable_txn().await?;

        let completed_rows = self.get_completed_rows(&mut tx).await?;
        let completed_agg_row_count = completed_rows.len();
        let completed_kafka_payloads = self.serialize_completed_rows(completed_rows)?;

        let failed_rows = self.get_failed_rows(&mut tx).await?;
        let failed_agg_row_count = failed_rows.len();
        let failed_kafka_payloads = self.serialize_failed_rows(failed_rows)?;

        let mut all_kafka_payloads = completed_kafka_payloads;
        all_kafka_payloads.extend(failed_kafka_payloads.into_iter());

        let mut rows_deleted: u64 = 0;
        if !all_kafka_payloads.is_empty() {
            self.send_messages_to_kafka(all_kafka_payloads).await?;
            rows_deleted = self.delete_observed_rows(&mut tx).await?;
            self.commit_txn(tx).await?;
        }

        debug!(
            "WebhookCleaner finished cleanup, deleted {} rows ({} completed+aggregated, {} failed+aggregated)",
            rows_deleted, completed_agg_row_count, failed_agg_row_count
        );

        Ok(())
    }
}

#[async_trait]
impl Cleaner for WebhookCleaner {
    async fn cleanup(&self) {
        match self.cleanup_impl().await {
            Ok(_) => {}
            Err(error) => {
                error!(error = ?error, "WebhookCleaner::cleanup failed");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config;
    use crate::kafka_producer::{create_kafka_producer, KafkaContext};
    use rdkafka::mocking::MockCluster;
    use rdkafka::producer::{DefaultProducerContext, FutureProducer};
    use sqlx::PgPool;

    const APP_METRICS_TOPIC: &str = "app_metrics";

    async fn create_mock_kafka() -> (
        MockCluster<'static, DefaultProducerContext>,
        FutureProducer<KafkaContext>,
    ) {
        let cluster = MockCluster::new(1).expect("failed to create mock brokers");

        let config = config::KafkaConfig {
            kafka_producer_linger_ms: 0,
            kafka_producer_queue_mib: 50,
            kafka_message_timeout_ms: 5000,
            kafka_compression_codec: "none".to_string(),
            kafka_hosts: cluster.bootstrap_servers(),
            app_metrics_topic: APP_METRICS_TOPIC.to_string(),
            plugin_log_entries_topic: "plugin_log_entries".to_string(),
            kafka_tls: false,
        };

        (
            cluster,
            create_kafka_producer(&config)
                .await
                .expect("failed to create mocked kafka producer"),
        )
    }

    #[sqlx::test(migrations = "../migrations", fixtures("webhook_cleanup"))]
    async fn test_cleanup_impl(db: PgPool) {
        let (mock_cluster, mock_producer) = create_mock_kafka().await;
        mock_cluster
            .create_topic(APP_METRICS_TOPIC, 1, 1)
            .expect("failed to create mock app_metrics topic");

        let table_name = "job_queue";
        let queue_name = "webhooks";

        let webhook_cleaner = WebhookCleaner::new_from_pool(
            &queue_name,
            &table_name,
            db,
            mock_producer,
            APP_METRICS_TOPIC.to_owned(),
        )
        .expect("unable to create webhook cleaner");

        let _ = webhook_cleaner
            .cleanup_impl()
            .await
            .expect("webbook cleanup_impl failed");

        // TODO: I spent a lot of time trying to get the mock Kafka consumer to work, but I think
        // I've identified an issue with the rust-rdkafka library:
        //   https://github.com/fede1024/rust-rdkafka/issues/629#issuecomment-1863555417
        //
        // I wanted to test the messages put on the AppMetrics topic, but I think we need to figure
        // out that issue about in order to do so. (Capture uses the MockProducer but not a
        // Consumer, fwiw.)
        //
        // For now, I'll probably have to make `cleanup_impl` return the row information so at
        // least we can inspect that for correctness.
    }

    // #[sqlx::test]
    // async fn test_serializable_isolation() {
    //   TODO: I'm going to add a test that verifies new rows aren't visible during the txn.
    // }
}
