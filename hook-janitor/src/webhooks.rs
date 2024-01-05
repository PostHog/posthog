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
    plugin_config_id: u32,
    #[sqlx(json)]
    last_error: WebhookJobError,
    #[sqlx(try_from = "i64")]
    failures: u32,
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
    completed_agg_row_count: usize,
    failed_agg_row_count: usize,
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
            SELECT DATE_TRUNC('hour', last_attempt_finished_at) AS hour,
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

    async fn get_failed_rows(&self, tx: &mut SerializableTxn<'_>) -> Result<Vec<FailedRow>> {
        let base_query = format!(
            r#"
            SELECT DATE_TRUNC('hour', last_attempt_finished_at) AS hour,
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

    async fn cleanup_impl(&self) -> Result<CleanupStats> {
        debug!("WebhookCleaner starting cleanup");

        // Note that we select all completed and failed rows without any pagination at the moment.
        // We aggregrate as much as possible with GROUP BY, truncating the timestamp down to the
        // hour just like App Metrics does. A completed row is 24 bytes (and aggregates an entire
        // hour per `plugin_config_id`), and a failed row is 104 bytes + the error message length
        // (and aggregates an entire hour per `plugin_config_id` per `error`), so we can fit a lot
        // of rows in memory. It seems unlikely we'll need to paginate, but that can be added in the
        // future if necessary.

        let mut tx = self.start_serializable_txn().await?;

        let completed_agg_row_count = {
            let completed_rows = self.get_completed_rows(&mut tx).await?;
            let row_count = completed_rows.len();
            let completed_app_metrics: Vec<AppMetric> =
                completed_rows.into_iter().map(Into::into).collect();
            self.send_metrics_to_kafka(completed_app_metrics).await?;
            row_count
        };

        let failed_agg_row_count = {
            let failed_rows = self.get_failed_rows(&mut tx).await?;
            let row_count = failed_rows.len();
            let failed_app_metrics: Vec<AppMetric> =
                failed_rows.into_iter().map(Into::into).collect();
            self.send_metrics_to_kafka(failed_app_metrics).await?;
            row_count
        };

        let mut rows_processed = 0;
        if completed_agg_row_count + failed_agg_row_count != 0 {
            rows_processed = self.delete_observed_rows(&mut tx).await?;
            self.commit_txn(tx).await?;
        }

        Ok(CleanupStats {
            rows_processed,
            completed_agg_row_count,
            failed_agg_row_count,
        })
    }
}

#[async_trait]
impl Cleaner for WebhookCleaner {
    async fn cleanup(&self) {
        match self.cleanup_impl().await {
            Ok(stats) => {
                if stats.rows_processed > 0 {
                    debug!(
                        rows_processed = stats.rows_processed,
                        completed_agg_row_count = stats.completed_agg_row_count,
                        failed_agg_row_count = stats.failed_agg_row_count,
                        "WebhookCleaner::cleanup finished"
                    );
                } else {
                    debug!("WebhookCleaner finished cleanup, there were no rows to process");
                }
            }
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
    use hook_common::kafka_messages::app_metrics::{
        Error as WebhookError, ErrorDetails, ErrorType,
    };
    use hook_common::pgqueue::{NewJob, PgJob, PgQueue, PgQueueJob};
    use hook_common::webhook::{HttpMethod, WebhookJobMetadata, WebhookJobParameters};
    use rdkafka::consumer::{Consumer, StreamConsumer};
    use rdkafka::mocking::MockCluster;
    use rdkafka::producer::{DefaultProducerContext, FutureProducer};
    use rdkafka::{ClientConfig, Message};
    use sqlx::{PgPool, Row};
    use std::collections::HashMap;
    use std::str::FromStr;

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

        let webhook_cleaner = WebhookCleaner::new_from_pool(
            &"webhooks",
            &"job_queue",
            db,
            mock_producer,
            APP_METRICS_TOPIC.to_owned(),
        )
        .expect("unable to create webhook cleaner");

        let cleanup_stats = webhook_cleaner
            .cleanup_impl()
            .await
            .expect("webbook cleanup_impl failed");

        // Rows from other queues and rows that are not 'completed' or 'failed' should not be
        // processed.
        assert_eq!(cleanup_stats.rows_processed, 11);

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
                successes: 2,
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
                failures: 2,
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

    #[sqlx::test(migrations = "../migrations", fixtures("webhook_cleanup"))]
    async fn test_serializable_isolation(db: PgPool) {
        let (_, mock_producer) = create_mock_kafka().await;
        let webhook_cleaner = WebhookCleaner::new_from_pool(
            &"webhooks",
            &"job_queue",
            db.clone(),
            mock_producer,
            APP_METRICS_TOPIC.to_owned(),
        )
        .expect("unable to create webhook cleaner");

        let queue = PgQueue::new_from_pool("webhooks", "job_queue", db.clone())
            .await
            .expect("failed to connect to local test postgresql database");

        async fn get_count_from_new_conn(db: &PgPool, status: &str) -> i64 {
            let mut conn = db.acquire().await.unwrap();
            let count: i64 = sqlx::query(
                "SELECT count(*) FROM job_queue WHERE queue = 'webhooks' AND status = $1::job_status",
            )
            .bind(&status)
            .fetch_one(&mut *conn)
            .await
            .unwrap()
            .get(0);
            count
        }

        // Important! Serializable txn is started here.
        let mut tx = webhook_cleaner.start_serializable_txn().await.unwrap();
        webhook_cleaner.get_completed_rows(&mut tx).await.unwrap();
        webhook_cleaner.get_failed_rows(&mut tx).await.unwrap();

        // All 13 rows in the queue are visible from outside the txn.
        // The 11 the cleaner will process, plus 1 available and 1 running.
        assert_eq!(get_count_from_new_conn(&db, "completed").await, 5);
        assert_eq!(get_count_from_new_conn(&db, "failed").await, 6);
        assert_eq!(get_count_from_new_conn(&db, "available").await, 1);
        assert_eq!(get_count_from_new_conn(&db, "running").await, 1);

        {
            // The fixtures include an available job, so let's complete it while the txn is open.
            let webhook_job: PgJob<WebhookJobParameters, WebhookJobMetadata> = queue
                .dequeue(&"worker_id")
                .await
                .expect("failed to dequeue job")
                .expect("didn't find a job to dequeue");
            webhook_job
                .complete()
                .await
                .expect("failed to complete job");
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
            let webhook_job: PgJob<WebhookJobParameters, WebhookJobMetadata> = queue
                .dequeue(&"worker_id")
                .await
                .expect("failed to dequeue job")
                .expect("didn't find a job to dequeue");
            webhook_job
                .complete()
                .await
                .expect("failed to complete job");
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
        assert_eq!(get_count_from_new_conn(&db, "completed").await, 7);
        assert_eq!(get_count_from_new_conn(&db, "available").await, 1);

        let rows_processed = webhook_cleaner.delete_observed_rows(&mut tx).await.unwrap();
        // The 11 rows that were in the queue when the txn started should be deleted.
        assert_eq!(rows_processed, 11);

        // We haven't committed, so the rows are still visible from outside the txn.
        assert_eq!(get_count_from_new_conn(&db, "completed").await, 7);
        assert_eq!(get_count_from_new_conn(&db, "available").await, 1);

        webhook_cleaner.commit_txn(tx).await.unwrap();

        // We have committed, what remains are:
        // * The 1 available job we completed while the txn was open.
        // * The 2 brand new jobs we added while the txn was open.
        // * The 1 running job that didn't change.
        assert_eq!(get_count_from_new_conn(&db, "completed").await, 2);
        assert_eq!(get_count_from_new_conn(&db, "failed").await, 0);
        assert_eq!(get_count_from_new_conn(&db, "available").await, 1);
        assert_eq!(get_count_from_new_conn(&db, "running").await, 1);
    }
}
