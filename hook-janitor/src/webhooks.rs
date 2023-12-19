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

    async fn start_serializable_txn(&self) -> Result<Transaction<'_, Postgres>> {
        let mut tx = self
            .pg_pool
            .begin()
            .await
            .map_err(|e| WebhookCleanerError::StartTxnError { error: e })?;

        // We use serializable isolation so that we observe a snapshot of the DB at the time we
        // start the cleanup process. This prevents us from accidentally deleting rows that are
        // added (or become 'completed' or 'failed') after we start the cleanup process.
        sqlx::query("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            .execute(&mut *tx)
            .await
            .map_err(|e| WebhookCleanerError::StartTxnError { error: e })?;

        Ok(tx)
    }

    async fn get_completed_rows(
        &self,
        tx: &mut Transaction<'_, Postgres>,
    ) -> Result<Vec<CompletedRow>> {
        let base_query = format!(
            r#"
            SELECT DATE_TRUNC('hour', finished_at) AS hour,
                metadata->>'team_id' AS team_id,
                metadata->>'plugin_config_id' AS plugin_config_id,
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
            .fetch_all(&mut **tx)
            .await
            .map_err(|e| WebhookCleanerError::GetCompletedRowsError { error: e })?;

        Ok(rows)
    }

    async fn serialize_completed_rows(
        &self,
        completed_rows: Vec<CompletedRow>,
    ) -> Result<Vec<String>> {
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

    async fn get_failed_rows(&self, tx: &mut Transaction<'_, Postgres>) -> Result<Vec<FailedRow>> {
        let base_query = format!(
            r#"
            SELECT DATE_TRUNC('hour', finished_at) AS hour,
                   metadata->>'team_id' AS team_id,
                   metadata->>'plugin_config_id' AS plugin_config_id,
                   errors[-1] AS last_error,
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
            .fetch_all(&mut **tx)
            .await
            .map_err(|e| WebhookCleanerError::GetFailedRowsError { error: e })?;

        Ok(rows)
    }

    async fn serialize_failed_rows(&self, failed_rows: Vec<FailedRow>) -> Result<Vec<String>> {
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

    async fn delete_observed_rows(&self, tx: &mut Transaction<'_, Postgres>) -> Result<u64> {
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
            .execute(&mut **tx)
            .await
            .map_err(|e| WebhookCleanerError::DeleteRowsError { error: e })?;

        Ok(result.rows_affected())
    }

    async fn commit_txn(&self, tx: Transaction<'_, Postgres>) -> Result<()> {
        tx.commit()
            .await
            .map_err(|e| WebhookCleanerError::CommitTxnError { error: e })?;

        Ok(())
    }

    async fn cleanup_impl(&self) -> Result<()> {
        debug!("WebhookCleaner starting cleanup");

        // Note that we select all completed and failed rows without any pagination at the moment.
        // We aggregrate as much as possible with GROUP BY, truncating the timestamp down to the
        // hour just like App Metrics does. A completed row is 24 bytes (and aggregates an entire
        // hour per `plugin_config_id`), and a failed row is 104 + the message length (and
        // aggregates an entire hour per `plugin_config_id` per `error`), so we can fit a lot of
        // rows in memory. It seems unlikely we'll need to paginate, but that can be added in the
        // future if necessary.

        let mut tx = self.start_serializable_txn().await?;
        let completed_rows = self.get_completed_rows(&mut tx).await?;
        let mut payloads = self.serialize_completed_rows(completed_rows).await?;
        let failed_rows = self.get_failed_rows(&mut tx).await?;
        let mut failed_payloads = self.serialize_failed_rows(failed_rows).await?;
        payloads.append(&mut failed_payloads);
        let mut rows_deleted: u64 = 0;
        if !payloads.is_empty() {
            self.send_messages_to_kafka(payloads).await?;
            rows_deleted = self.delete_observed_rows(&mut tx).await?;
            self.commit_txn(tx).await?;
        }

        debug!(
            "WebhookCleaner finished cleanup, deleted {} rows",
            rows_deleted
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
    #[tokio::test]
    async fn test() {}
}
