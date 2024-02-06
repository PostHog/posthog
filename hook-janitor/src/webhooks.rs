use std::str::FromStr;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use futures::future::join_all;
use hook_common::webhook::WebhookJobError;
use rdkafka::error::KafkaError;
use rdkafka::producer::{FutureProducer, FutureRecord};
use serde_json::error::Error as SerdeError;
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions, Postgres};
use sqlx::types::{chrono, Uuid};
use sqlx::{Row, Transaction};
use thiserror::Error;
use tracing::{debug, error, info};

use crate::cleanup::Cleaner;
use crate::kafka_producer::KafkaContext;

use hook_common::kafka_messages::app_metrics::{AppMetric, AppMetricCategory};
use hook_common::metrics::get_current_timestamp_seconds;

#[derive(Error, Debug)]
pub enum WebhookCleanerError {
    #[error("failed to create postgres pool: {error}")]
    PoolCreationError { error: sqlx::Error },
    #[error("failed to acquire conn: {error}")]
    AcquireConnError { error: sqlx::Error },
    #[error("failed to acquire conn and start txn: {error}")]
    StartTxnError { error: sqlx::Error },
    #[error("failed to get queue depth: {error}")]
    GetQueueDepthError { error: sqlx::Error },
    #[error("failed to get row count: {error}")]
    GetRowCountError { error: sqlx::Error },
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
    #[error("attempted to delete a different number of rows than expected")]
    DeleteConsistencyError,
    #[error("failed to rollback txn: {error}")]
    RollbackTxnError { error: sqlx::Error },
    #[error("failed to commit txn: {error}")]
    CommitTxnError { error: sqlx::Error },
}

type Result<T, E = WebhookCleanerError> = std::result::Result<T, E>;

pub struct WebhookCleaner {
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
    plugin_config_id: i32,
    #[sqlx(try_from = "i64")]
    successes: u32,
}

impl From<CompletedRow> for AppMetric {
    fn from(row: CompletedRow) -> Self {
        AppMetric {
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
        }
    }
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
    plugin_config_id: i32,
    #[sqlx(json)]
    last_error: WebhookJobError,
    #[sqlx(try_from = "i64")]
    failures: u32,
}

#[derive(sqlx::FromRow, Debug)]
struct QueueDepth {
    oldest_scheduled_at_untried: DateTime<Utc>,
    count_untried: i64,
    oldest_scheduled_at_retries: DateTime<Utc>,
    count_retries: i64,
}

impl From<FailedRow> for AppMetric {
    fn from(row: FailedRow) -> Self {
        AppMetric {
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
        }
    }
}

// A simple wrapper type that ensures we don't use any old Transaction object when we need one
// that has set the isolation level to serializable.
struct SerializableTxn<'a>(Transaction<'a, Postgres>);

struct CleanupStats {
    rows_processed: u64,
    completed_row_count: u64,
    completed_agg_row_count: u64,
    failed_row_count: u64,
    failed_agg_row_count: u64,
}

impl WebhookCleaner {
    pub fn new(
        database_url: &str,
        kafka_producer: FutureProducer<KafkaContext>,
        app_metrics_topic: String,
    ) -> Result<Self> {
        let options = PgConnectOptions::from_str(database_url)
            .map_err(|error| WebhookCleanerError::PoolCreationError { error })?
            .application_name("hook-janitor");
        let pg_pool = PgPoolOptions::new()
            .acquire_timeout(Duration::from_secs(10))
            .connect_lazy_with(options);

        Ok(Self {
            pg_pool,
            kafka_producer,
            app_metrics_topic,
        })
    }

    #[allow(dead_code)] // This is used in tests.
    pub fn new_from_pool(
        pg_pool: PgPool,
        kafka_producer: FutureProducer<KafkaContext>,
        app_metrics_topic: String,
    ) -> Result<Self> {
        Ok(Self {
            pg_pool,
            kafka_producer,
            app_metrics_topic,
        })
    }

    async fn get_queue_depth(&self) -> Result<QueueDepth> {
        let mut conn = self
            .pg_pool
            .acquire()
            .await
            .map_err(|e| WebhookCleanerError::AcquireConnError { error: e })?;

        let base_query = r#"
        SELECT
            COALESCE(MIN(CASE WHEN attempt = 0 THEN scheduled_at END), now()) AS oldest_scheduled_at_untried,
            COALESCE(SUM(CASE WHEN attempt = 0 THEN 1 ELSE 0 END), 0) AS count_untried,
            COALESCE(MIN(CASE WHEN attempt > 0 THEN scheduled_at END), now()) AS oldest_scheduled_at_retries,
            COALESCE(SUM(CASE WHEN attempt > 0 THEN 1 ELSE 0 END), 0) AS count_retries
        FROM job_queue
        WHERE status = 'available';
        "#;

        let row = sqlx::query_as::<_, QueueDepth>(base_query)
            .fetch_one(&mut *conn)
            .await
            .map_err(|e| WebhookCleanerError::GetQueueDepthError { error: e })?;

        Ok(row)
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

    async fn get_row_count_for_status(
        &self,
        tx: &mut SerializableTxn<'_>,
        status: &str,
    ) -> Result<u64> {
        let base_query = r#"
            SELECT count(*) FROM job_queue
            WHERE status = $1::job_status;
            "#;

        let count: i64 = sqlx::query(base_query)
            .bind(status)
            .fetch_one(&mut *tx.0)
            .await
            .map_err(|e| WebhookCleanerError::GetRowCountError { error: e })?
            .get(0);

        Ok(count as u64)
    }

    async fn get_completed_agg_rows(
        &self,
        tx: &mut SerializableTxn<'_>,
    ) -> Result<Vec<CompletedRow>> {
        let base_query = r#"
            SELECT DATE_TRUNC('hour', last_attempt_finished_at) AS hour,
                (metadata->>'team_id')::bigint AS team_id,
                (metadata->>'plugin_config_id')::bigint AS plugin_config_id,
                count(*) as successes
            FROM job_queue
            WHERE status = 'completed'
            GROUP BY hour, team_id, plugin_config_id
            ORDER BY hour, team_id, plugin_config_id;
        "#;

        let rows = sqlx::query_as::<_, CompletedRow>(base_query)
            .fetch_all(&mut *tx.0)
            .await
            .map_err(|e| WebhookCleanerError::GetCompletedRowsError { error: e })?;

        Ok(rows)
    }

    async fn get_failed_agg_rows(&self, tx: &mut SerializableTxn<'_>) -> Result<Vec<FailedRow>> {
        let base_query = r#"
            SELECT DATE_TRUNC('hour', last_attempt_finished_at) AS hour,
                   (metadata->>'team_id')::bigint AS team_id,
                   (metadata->>'plugin_config_id')::bigint AS plugin_config_id,
                   errors[array_upper(errors, 1)] AS last_error,
                   count(*) as failures
            FROM job_queue
            WHERE status = 'failed'
            GROUP BY hour, team_id, plugin_config_id, last_error
            ORDER BY hour, team_id, plugin_config_id, last_error;
        "#;

        let rows = sqlx::query_as::<_, FailedRow>(base_query)
            .fetch_all(&mut *tx.0)
            .await
            .map_err(|e| WebhookCleanerError::GetFailedRowsError { error: e })?;

        Ok(rows)
    }

    async fn send_metrics_to_kafka(&self, metrics: Vec<AppMetric>) -> Result<()> {
        if metrics.is_empty() {
            return Ok(());
        }

        let payloads: Vec<String> = metrics
            .into_iter()
            .map(|metric| serde_json::to_string(&metric))
            .collect::<Result<Vec<String>, SerdeError>>()
            .map_err(|e| WebhookCleanerError::SerializeRowsError { error: e })?;

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
        let base_query = r#"
            DELETE FROM job_queue
            WHERE status IN ('failed', 'completed')
        "#;

        let result = sqlx::query(base_query)
            .execute(&mut *tx.0)
            .await
            .map_err(|e| WebhookCleanerError::DeleteRowsError { error: e })?;

        Ok(result.rows_affected())
    }

    async fn rollback_txn(&self, tx: SerializableTxn<'_>) -> Result<()> {
        tx.0.rollback()
            .await
            .map_err(|e| WebhookCleanerError::RollbackTxnError { error: e })?;

        Ok(())
    }

    async fn commit_txn(&self, tx: SerializableTxn<'_>) -> Result<()> {
        tx.0.commit()
            .await
            .map_err(|e| WebhookCleanerError::CommitTxnError { error: e })?;

        Ok(())
    }

    async fn cleanup_impl(&self) -> Result<CleanupStats> {
        debug!("WebhookCleaner starting cleanup");

        // Note that we select all completed and failed rows without any pagination at the moment.
        // We aggregrate as much as possible with GROUP BY, truncating the timestamp down to the
        // hour just like App Metrics does. A completed row is 24 bytes (and aggregates an entire
        // hour per `plugin_config_id`), and a failed row is 104 bytes + the error message length
        // (and aggregates an entire hour per `plugin_config_id` per `error`), so we can fit a lot
        // of rows in memory. It seems unlikely we'll need to paginate, but that can be added in the
        // future if necessary.

        let untried_status = [("status", "untried")];
        let retries_status = [("status", "retries")];

        let queue_depth = self.get_queue_depth().await?;
        metrics::gauge!("queue_depth_oldest_scheduled", &untried_status)
            .set(queue_depth.oldest_scheduled_at_untried.timestamp() as f64);
        metrics::gauge!("queue_depth", &untried_status).set(queue_depth.count_untried as f64);
        metrics::gauge!("queue_depth_oldest_scheduled", &retries_status)
            .set(queue_depth.oldest_scheduled_at_retries.timestamp() as f64);
        metrics::gauge!("queue_depth", &retries_status).set(queue_depth.count_retries as f64);

        let mut tx = self.start_serializable_txn().await?;

        let (completed_row_count, completed_agg_row_count) = {
            let completed_row_count = self.get_row_count_for_status(&mut tx, "completed").await?;
            let completed_agg_rows = self.get_completed_agg_rows(&mut tx).await?;
            let agg_row_count = completed_agg_rows.len() as u64;
            let completed_app_metrics: Vec<AppMetric> =
                completed_agg_rows.into_iter().map(Into::into).collect();
            self.send_metrics_to_kafka(completed_app_metrics).await?;
            (completed_row_count, agg_row_count)
        };

        let (failed_row_count, failed_agg_row_count) = {
            let failed_row_count = self.get_row_count_for_status(&mut tx, "failed").await?;
            let failed_agg_rows = self.get_failed_agg_rows(&mut tx).await?;
            let agg_row_count = failed_agg_rows.len() as u64;
            let failed_app_metrics: Vec<AppMetric> =
                failed_agg_rows.into_iter().map(Into::into).collect();
            self.send_metrics_to_kafka(failed_app_metrics).await?;
            (failed_row_count, agg_row_count)
        };

        let mut rows_deleted = 0;
        if completed_agg_row_count + failed_agg_row_count != 0 {
            rows_deleted = self.delete_observed_rows(&mut tx).await?;

            if rows_deleted != completed_row_count + failed_row_count {
                // This should never happen, but if it does, we want to know about it (and abort the
                // txn).
                error!(
                    attempted_rows_deleted = rows_deleted,
                    completed_row_count = completed_row_count,
                    failed_row_count = failed_row_count,
                    "WebhookCleaner::cleanup attempted to delete a different number of rows than expected"
                );

                self.rollback_txn(tx).await?;

                return Err(WebhookCleanerError::DeleteConsistencyError);
            }

            self.commit_txn(tx).await?;
        }

        Ok(CleanupStats {
            rows_processed: rows_deleted,
            completed_row_count,
            completed_agg_row_count,
            failed_row_count,
            failed_agg_row_count,
        })
    }
}

#[async_trait]
impl Cleaner for WebhookCleaner {
    async fn cleanup(&self) {
        let start_time = Instant::now();
        metrics::counter!("webhook_cleanup_attempts",).increment(1);

        match self.cleanup_impl().await {
            Ok(stats) => {
                metrics::counter!("webhook_cleanup_success",).increment(1);
                metrics::gauge!("webhook_cleanup_last_success_timestamp",)
                    .set(get_current_timestamp_seconds());

                if stats.rows_processed > 0 {
                    let elapsed_time = start_time.elapsed().as_secs_f64();
                    metrics::histogram!("webhook_cleanup_duration").record(elapsed_time);
                    metrics::counter!("webhook_cleanup_rows_processed",)
                        .increment(stats.rows_processed);
                    metrics::counter!("webhook_cleanup_completed_row_count",)
                        .increment(stats.completed_row_count);
                    metrics::counter!("webhook_cleanup_completed_agg_row_count",)
                        .increment(stats.completed_agg_row_count);
                    metrics::counter!("webhook_cleanup_failed_row_count",)
                        .increment(stats.failed_row_count);
                    metrics::counter!("webhook_cleanup_failed_agg_row_count",)
                        .increment(stats.failed_agg_row_count);

                    info!(
                        rows_processed = stats.rows_processed,
                        completed_row_count = stats.completed_row_count,
                        completed_agg_row_count = stats.completed_agg_row_count,
                        failed_row_count = stats.failed_row_count,
                        failed_agg_row_count = stats.failed_agg_row_count,
                        "WebhookCleaner::cleanup finished"
                    );
                } else {
                    debug!("WebhookCleaner finished cleanup, there were no rows to process");
                }
            }
            Err(error) => {
                metrics::counter!("webhook_cleanup_failures",).increment(1);
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
    use hook_common::health::HealthRegistry;
    use hook_common::kafka_messages::app_metrics::{
        Error as WebhookError, ErrorDetails, ErrorType,
    };
    use hook_common::pgqueue::PgQueueJob;
    use hook_common::pgqueue::{NewJob, PgQueue, PgTransactionBatch};
    use hook_common::webhook::{HttpMethod, WebhookJobMetadata, WebhookJobParameters};
    use rdkafka::consumer::{Consumer, StreamConsumer};
    use rdkafka::mocking::MockCluster;
    use rdkafka::producer::{DefaultProducerContext, FutureProducer};
    use rdkafka::types::{RDKafkaApiKey, RDKafkaRespErr};
    use rdkafka::{ClientConfig, Message};
    use sqlx::{PgPool, Row};
    use std::collections::HashMap;
    use std::str::FromStr;

    const APP_METRICS_TOPIC: &str = "app_metrics";

    async fn create_mock_kafka() -> (
        MockCluster<'static, DefaultProducerContext>,
        FutureProducer<KafkaContext>,
    ) {
        let registry = HealthRegistry::new("liveness");
        let handle = registry
            .register("one".to_string(), time::Duration::seconds(30))
            .await;
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
            create_kafka_producer(&config, handle)
                .await
                .expect("failed to create mocked kafka producer"),
        )
    }

    fn check_app_metric_vector_equality(v1: &[AppMetric], v2: &[AppMetric]) {
        // Ignores `error_uuid`s.
        assert_eq!(v1.len(), v2.len());
        for (item1, item2) in v1.iter().zip(v2) {
            let mut item1 = item1.clone();
            item1.error_uuid = None;
            let mut item2 = item2.clone();
            item2.error_uuid = None;
            assert_eq!(item1, item2);
        }
    }

    #[sqlx::test(migrations = "../migrations", fixtures("webhook_cleanup"))]
    async fn test_cleanup_impl(db: PgPool) {
        let (mock_cluster, mock_producer) = create_mock_kafka().await;
        mock_cluster
            .create_topic(APP_METRICS_TOPIC, 1, 1)
            .expect("failed to create mock app_metrics topic");

        let consumer: StreamConsumer = ClientConfig::new()
            .set("bootstrap.servers", mock_cluster.bootstrap_servers())
            .set("group.id", "mock")
            .set("auto.offset.reset", "earliest")
            .create()
            .expect("failed to create mock consumer");
        consumer.subscribe(&[APP_METRICS_TOPIC]).unwrap();

        let webhook_cleaner =
            WebhookCleaner::new_from_pool(db, mock_producer, APP_METRICS_TOPIC.to_owned())
                .expect("unable to create webhook cleaner");

        let cleanup_stats = webhook_cleaner
            .cleanup_impl()
            .await
            .expect("webbook cleanup_impl failed");

        // Rows that are not 'completed' or 'failed' should not be processed.
        assert_eq!(cleanup_stats.rows_processed, 13);

        let mut received_app_metrics = Vec::new();
        for _ in 0..(cleanup_stats.completed_agg_row_count + cleanup_stats.failed_agg_row_count) {
            let kafka_msg = consumer.recv().await.unwrap();
            let payload_str = String::from_utf8(kafka_msg.payload().unwrap().to_vec()).unwrap();
            let app_metric: AppMetric = serde_json::from_str(&payload_str).unwrap();
            received_app_metrics.push(app_metric);
        }

        let expected_app_metrics = vec![
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T20:00:00Z").unwrap(),
                team_id: 1,
                plugin_config_id: 2,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 3,
                successes_on_retry: 0,
                failures: 0,
                error_uuid: None,
                error_type: None,
                error_details: None,
            },
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T20:00:00Z").unwrap(),
                team_id: 1,
                plugin_config_id: 3,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 1,
                successes_on_retry: 0,
                failures: 0,
                error_uuid: None,
                error_type: None,
                error_details: None,
            },
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T20:00:00Z").unwrap(),
                team_id: 2,
                plugin_config_id: 4,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 1,
                successes_on_retry: 0,
                failures: 0,
                error_uuid: None,
                error_type: None,
                error_details: None,
            },
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T21:00:00Z").unwrap(),
                team_id: 1,
                plugin_config_id: 2,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 1,
                successes_on_retry: 0,
                failures: 0,
                error_uuid: None,
                error_type: None,
                error_details: None,
            },
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T20:00:00Z").unwrap(),
                team_id: 1,
                plugin_config_id: 2,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 0,
                successes_on_retry: 0,
                failures: 1,
                error_uuid: Some(Uuid::parse_str("018c8935-d038-714a-957c-0df43d42e377").unwrap()),
                error_type: Some(ErrorType::ConnectionError),
                error_details: Some(ErrorDetails {
                    error: WebhookError {
                        name: "Connection Error".to_owned(),
                        message: None,
                        stack: None,
                    },
                }),
            },
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T20:00:00Z").unwrap(),
                team_id: 1,
                plugin_config_id: 2,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 0,
                successes_on_retry: 0,
                failures: 3,
                error_uuid: Some(Uuid::parse_str("018c8935-d038-714a-957c-0df43d42e377").unwrap()),
                error_type: Some(ErrorType::TimeoutError),
                error_details: Some(ErrorDetails {
                    error: WebhookError {
                        name: "Timeout".to_owned(),
                        message: None,
                        stack: None,
                    },
                }),
            },
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T20:00:00Z").unwrap(),
                team_id: 1,
                plugin_config_id: 3,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 0,
                successes_on_retry: 0,
                failures: 1,
                error_uuid: Some(Uuid::parse_str("018c8935-d038-714a-957c-0df43d42e377").unwrap()),
                error_type: Some(ErrorType::TimeoutError),
                error_details: Some(ErrorDetails {
                    error: WebhookError {
                        name: "Timeout".to_owned(),
                        message: None,
                        stack: None,
                    },
                }),
            },
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T20:00:00Z").unwrap(),
                team_id: 2,
                plugin_config_id: 4,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 0,
                successes_on_retry: 0,
                failures: 1,
                error_uuid: Some(Uuid::parse_str("018c8935-d038-714a-957c-0df43d42e377").unwrap()),
                error_type: Some(ErrorType::TimeoutError),
                error_details: Some(ErrorDetails {
                    error: WebhookError {
                        name: "Timeout".to_owned(),
                        message: None,
                        stack: None,
                    },
                }),
            },
            AppMetric {
                timestamp: DateTime::<Utc>::from_str("2023-12-19T21:00:00Z").unwrap(),
                team_id: 1,
                plugin_config_id: 2,
                job_id: None,
                category: AppMetricCategory::Webhook,
                successes: 0,
                successes_on_retry: 0,
                failures: 1,
                error_uuid: Some(Uuid::parse_str("018c8935-d038-714a-957c-0df43d42e377").unwrap()),
                error_type: Some(ErrorType::TimeoutError),
                error_details: Some(ErrorDetails {
                    error: WebhookError {
                        name: "Timeout".to_owned(),
                        message: None,
                        stack: None,
                    },
                }),
            },
        ];

        check_app_metric_vector_equality(&expected_app_metrics, &received_app_metrics);
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn test_cleanup_impl_empty_queue(db: PgPool) {
        let (mock_cluster, mock_producer) = create_mock_kafka().await;
        mock_cluster
            .create_topic(APP_METRICS_TOPIC, 1, 1)
            .expect("failed to create mock app_metrics topic");

        // No payload should be produced to kafka as the queue is empty.
        // Set a non-retriable produce error that would bubble-up when cleanup_impl is called.
        let err = [RDKafkaRespErr::RD_KAFKA_RESP_ERR_MSG_SIZE_TOO_LARGE; 1];
        mock_cluster.request_errors(RDKafkaApiKey::Produce, &err);

        let consumer: StreamConsumer = ClientConfig::new()
            .set("bootstrap.servers", mock_cluster.bootstrap_servers())
            .set("group.id", "mock")
            .set("auto.offset.reset", "earliest")
            .create()
            .expect("failed to create mock consumer");
        consumer.subscribe(&[APP_METRICS_TOPIC]).unwrap();

        let webhook_cleaner =
            WebhookCleaner::new_from_pool(db, mock_producer, APP_METRICS_TOPIC.to_owned())
                .expect("unable to create webhook cleaner");

        let cleanup_stats = webhook_cleaner
            .cleanup_impl()
            .await
            .expect("webbook cleanup_impl failed");

        // Reported metrics are all zeroes
        assert_eq!(cleanup_stats.rows_processed, 0);
        assert_eq!(cleanup_stats.completed_row_count, 0);
        assert_eq!(cleanup_stats.completed_agg_row_count, 0);
        assert_eq!(cleanup_stats.failed_row_count, 0);
        assert_eq!(cleanup_stats.failed_agg_row_count, 0);
    }

    #[sqlx::test(migrations = "../migrations", fixtures("webhook_cleanup"))]
    async fn test_serializable_isolation(db: PgPool) {
        let (_, mock_producer) = create_mock_kafka().await;
        let webhook_cleaner =
            WebhookCleaner::new_from_pool(db.clone(), mock_producer, APP_METRICS_TOPIC.to_owned())
                .expect("unable to create webhook cleaner");

        let queue = PgQueue::new_from_pool("webhooks", db.clone()).await;

        async fn get_count_from_new_conn(db: &PgPool, status: &str) -> i64 {
            let mut conn = db.acquire().await.unwrap();
            let count: i64 =
                sqlx::query("SELECT count(*) FROM job_queue WHERE status = $1::job_status")
                    .bind(&status)
                    .fetch_one(&mut *conn)
                    .await
                    .unwrap()
                    .get(0);
            count
        }

        // Important! Serializable txn is started here.
        let mut tx = webhook_cleaner.start_serializable_txn().await.unwrap();
        webhook_cleaner
            .get_completed_agg_rows(&mut tx)
            .await
            .unwrap();
        webhook_cleaner.get_failed_agg_rows(&mut tx).await.unwrap();

        // All 15 rows in the DB are visible from outside the txn.
        // The 13 the cleaner will process, plus 1 available and 1 running.
        assert_eq!(get_count_from_new_conn(&db, "completed").await, 6);
        assert_eq!(get_count_from_new_conn(&db, "failed").await, 7);
        assert_eq!(get_count_from_new_conn(&db, "available").await, 1);

        {
            // The fixtures include an available job, so let's complete it while the txn is open.
            let mut batch: PgTransactionBatch<'_, WebhookJobParameters, WebhookJobMetadata> = queue
                .dequeue_tx(&"worker_id", 1)
                .await
                .expect("failed to dequeue job")
                .expect("didn't find a job to dequeue");
            let webhook_job = batch.jobs.pop().unwrap();
            webhook_job
                .complete()
                .await
                .expect("failed to complete job");
            batch.commit().await.expect("failed to commit batch");
        }

        {
            // Enqueue and complete another job while the txn is open.
            let job_parameters = WebhookJobParameters {
                body: "foo".to_owned(),
                headers: HashMap::new(),
                method: HttpMethod::POST,
                url: "http://example.com".to_owned(),
            };
            let job_metadata = WebhookJobMetadata {
                team_id: 1,
                plugin_id: 2,
                plugin_config_id: 3,
            };
            let new_job = NewJob::new(1, job_metadata, job_parameters, &"target");
            queue.enqueue(new_job).await.expect("failed to enqueue job");
            let mut batch: PgTransactionBatch<'_, WebhookJobParameters, WebhookJobMetadata> = queue
                .dequeue_tx(&"worker_id", 1)
                .await
                .expect("failed to dequeue job")
                .expect("didn't find a job to dequeue");
            let webhook_job = batch.jobs.pop().unwrap();
            webhook_job
                .complete()
                .await
                .expect("failed to complete job");
            batch.commit().await.expect("failed to commit batch");
        }

        {
            // Enqueue another available job while the txn is open.
            let job_parameters = WebhookJobParameters {
                body: "foo".to_owned(),
                headers: HashMap::new(),
                method: HttpMethod::POST,
                url: "http://example.com".to_owned(),
            };
            let job_metadata = WebhookJobMetadata {
                team_id: 1,
                plugin_id: 2,
                plugin_config_id: 3,
            };
            let new_job = NewJob::new(1, job_metadata, job_parameters, &"target");
            queue.enqueue(new_job).await.expect("failed to enqueue job");
        }

        // There are now 2 more completed rows (jobs added above) than before, visible from outside the txn.
        assert_eq!(get_count_from_new_conn(&db, "completed").await, 8);
        assert_eq!(get_count_from_new_conn(&db, "available").await, 1);

        let rows_processed = webhook_cleaner.delete_observed_rows(&mut tx).await.unwrap();
        // The 13 rows in the DB when the txn started should be deleted.
        assert_eq!(rows_processed, 13);

        // We haven't committed, so the rows are still visible from outside the txn.
        assert_eq!(get_count_from_new_conn(&db, "completed").await, 8);
        assert_eq!(get_count_from_new_conn(&db, "available").await, 1);

        webhook_cleaner.commit_txn(tx).await.unwrap();

        // We have committed, what remains are:
        // * The 1 available job we completed while the txn was open.
        // * The 2 brand new jobs we added while the txn was open.
        // * The 1 running job that didn't change.
        assert_eq!(get_count_from_new_conn(&db, "completed").await, 2);
        assert_eq!(get_count_from_new_conn(&db, "failed").await, 0);
        assert_eq!(get_count_from_new_conn(&db, "available").await, 1);
    }
}
