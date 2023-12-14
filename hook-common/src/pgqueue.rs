//! # PgQueue
//!
//! A job queue implementation backed by a PostgreSQL table.
use std::str::FromStr;
use std::time;

use async_trait::async_trait;
use chrono;
use serde;
use sqlx::postgres::{PgPool, PgPoolOptions};
use thiserror::Error;

/// Enumeration of errors for operations with PgQueue.
/// Errors that can originate from sqlx and are wrapped by us to provide additional context.
#[derive(Error, Debug)]
pub enum PgQueueError {
    #[error("pool creation failed with: {error}")]
    PoolCreationError { error: sqlx::Error },
    #[error("connection failed with: {error}")]
    ConnectionError { error: sqlx::Error },
    #[error("{command} query failed with: {error}")]
    QueryError { command: String, error: sqlx::Error },
    #[error("{0} is not a valid JobStatus")]
    ParseJobStatusError(String),
    #[error("{0} is not a valid HttpMethod")]
    ParseHttpMethodError(String),
}

#[derive(Error, Debug)]
pub enum PgJobError<T> {
    #[error("retry is an invalid state for this PgJob: {error}")]
    RetryInvalidError { job: T, error: String },
    #[error("{command} query failed with: {error}")]
    QueryError { command: String, error: sqlx::Error },
    #[error("transaction {command} failed with: {error}")]
    TransactionError { command: String, error: sqlx::Error },
}

/// Enumeration of possible statuses for a Job.
#[derive(Debug, PartialEq, sqlx::Type)]
#[sqlx(type_name = "job_status")]
#[sqlx(rename_all = "lowercase")]
pub enum JobStatus {
    /// A job that is waiting in the queue to be picked up by a worker.
    Available,
    /// A job that was cancelled by a worker.
    Cancelled,
    /// A job that was successfully completed by a worker.
    Completed,
    /// A job that has
    Discarded,
    /// A job that was unsuccessfully completed by a worker.
    Failed,
    /// A job that was picked up by a worker and it's currentlly being run.
    Running,
}

/// Allow casting JobStatus from strings.
impl FromStr for JobStatus {
    type Err = PgQueueError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "available" => Ok(JobStatus::Available),
            "completed" => Ok(JobStatus::Completed),
            "failed" => Ok(JobStatus::Failed),
            "running" => Ok(JobStatus::Running),
            invalid => Err(PgQueueError::ParseJobStatusError(invalid.to_owned())),
        }
    }
}

/// JobParameters are stored and read to and from a JSONB field, so we accept anything that fits `sqlx::types::Json`.
pub type JobParameters<J> = sqlx::types::Json<J>;

/// JobMetadata are stored and read to and from a JSONB field, so we accept anything that fits `sqlx::types::Json`.
pub type JobMetadata<M> = sqlx::types::Json<M>;

/// A Job to be executed by a worker dequeueing a PgQueue.
#[derive(sqlx::FromRow, Debug)]
pub struct Job<J, M> {
    /// A unique id identifying a job.
    pub id: i64,
    /// A number corresponding to the current job attempt.
    pub attempt: i32,
    /// A datetime corresponding to when the job was attempted.
    pub attempted_at: chrono::DateTime<chrono::offset::Utc>,
    /// A vector of identifiers that have attempted this job. E.g. thread ids, pod names, etc...
    pub attempted_by: Vec<String>,
    /// A datetime corresponding to when the job was created.
    pub created_at: chrono::DateTime<chrono::offset::Utc>,
    /// The current job's number of max attempts.
    pub max_attempts: i32,
    /// Arbitrary job metadata stored as JSON.
    pub metadata: JobMetadata<M>,
    /// Arbitrary job parameters stored as JSON.
    pub parameters: JobParameters<J>,
    /// The queue this job belongs to.
    pub queue: String,
    /// The current status of the job.
    pub status: JobStatus,
    /// The target of the job. E.g. an endpoint or service we are trying to reach.
    pub target: String,
}

impl<J, M> Job<J, M> {
    /// Return true if this job attempt is greater or equal to the maximum number of possible attempts.
    pub fn is_gte_max_attempts(&self) -> bool {
        self.attempt >= self.max_attempts
    }

    /// Consume Job to retry it.
    /// This returns a RetryableJob that can be enqueued by PgQueue.
    ///
    /// # Arguments
    ///
    /// * `error`: Any JSON-serializable value to be stored as an error.
    fn retry<E: serde::Serialize>(self, error: E) -> RetryableJob<E> {
        RetryableJob {
            id: self.id,
            attempt: self.attempt,
            error: sqlx::types::Json(error),
            queue: self.queue,
        }
    }

    /// Consume Job to complete it.
    /// This returns a CompletedJob that can be marked as completed by PgQueue.
    fn complete(self) -> CompletedJob {
        CompletedJob {
            id: self.id,
            queue: self.queue,
        }
    }

    /// Consume Job to fail it.
    /// This returns a FailedJob that can be marked as failed by PgQueue.
    ///
    /// # Arguments
    ///
    /// * `error`: Any JSON-serializable value to be stored as an error.
    fn fail<E: serde::Serialize>(self, error: E) -> FailedJob<E> {
        FailedJob {
            id: self.id,
            error: sqlx::types::Json(error),
            queue: self.queue,
        }
    }
}

#[async_trait]
pub trait PgQueueJob {
    async fn complete(mut self) -> Result<CompletedJob, PgJobError<Box<Self>>>;

    async fn fail<E: serde::Serialize + std::marker::Sync + std::marker::Send>(
        mut self,
        error: E,
    ) -> Result<FailedJob<E>, PgJobError<Box<Self>>>;

    async fn retry<E: serde::Serialize + std::marker::Sync + std::marker::Send>(
        mut self,
        error: E,
        preferred_retry_interval: Option<time::Duration>,
    ) -> Result<RetryableJob<E>, PgJobError<Box<Self>>>;
}

/// A Job that can be updated in PostgreSQL.
#[derive(Debug)]
pub struct PgJob<J, M> {
    pub job: Job<J, M>,
    pub table: String,
    pub connection: sqlx::pool::PoolConnection<sqlx::postgres::Postgres>,
}

#[async_trait]
impl<J: std::marker::Send, M: std::marker::Send> PgQueueJob for PgJob<J, M> {
    async fn complete(mut self) -> Result<CompletedJob, PgJobError<Box<PgJob<J, M>>>> {
        let completed_job = self.job.complete();

        let base_query = format!(
            r#"
UPDATE
    "{0}"
SET
    finished_at = NOW(),
    status = 'completed'::job_status
WHERE
    "{0}".id = $2
    AND queue = $1
RETURNING
    "{0}".*
            "#,
            &self.table
        );

        sqlx::query(&base_query)
            .bind(&completed_job.queue)
            .bind(completed_job.id)
            .execute(&mut *self.connection)
            .await
            .map_err(|error| PgJobError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        Ok(completed_job)
    }

    async fn fail<E: serde::Serialize + std::marker::Sync + std::marker::Send>(
        mut self,
        error: E,
    ) -> Result<FailedJob<E>, PgJobError<Box<PgJob<J, M>>>> {
        let failed_job = self.job.fail(error);

        let base_query = format!(
            r#"
UPDATE
    "{0}"
SET
    finished_at = NOW(),
    status = 'failed'::job_status
    errors = array_append("{0}".errors, $3)
WHERE
    "{0}".id = $2
    AND queue = $1
RETURNING
    "{0}".*

            "#,
            &self.table
        );

        sqlx::query(&base_query)
            .bind(&failed_job.queue)
            .bind(failed_job.id)
            .bind(&failed_job.error)
            .execute(&mut *self.connection)
            .await
            .map_err(|error| PgJobError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        Ok(failed_job)
    }

    async fn retry<E: serde::Serialize + std::marker::Sync + std::marker::Send>(
        mut self,
        error: E,
        preferred_retry_interval: Option<time::Duration>,
    ) -> Result<RetryableJob<E>, PgJobError<Box<PgJob<J, M>>>> {
        if self.job.is_gte_max_attempts() {
            return Err(PgJobError::RetryInvalidError {
                job: Box::new(self),
                error: "Maximum attempts reached".to_owned(),
            });
        }
        let retryable_job = self.job.retry(error);

        let base_query = format!(
            r#"
UPDATE
    "{0}"
SET
    finished_at = NOW(),
    status = 'available'::job_status,
    scheduled_at = NOW() + $3,
    errors = array_append("{0}".errors, $4)
WHERE
    "{0}".id = $2
    AND queue = $1
RETURNING
    "{0}".*
            "#,
            &self.table
        );

        sqlx::query(&base_query)
            .bind(&retryable_job.queue)
            .bind(retryable_job.id)
            .bind(retry_interval)
            .bind(&retryable_job.error)
            .execute(&mut *self.connection)
            .await
            .map_err(|error| PgJobError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        Ok(retryable_job)
    }
}

/// A Job within an open PostgreSQL transaction.
/// This implementation allows 'hiding' the job from any other workers running SKIP LOCKED queries.
#[derive(Debug)]
pub struct PgTransactionJob<'c, J, M> {
    pub job: Job<J, M>,
    pub table: String,
    pub transaction: sqlx::Transaction<'c, sqlx::postgres::Postgres>,
}

#[async_trait]
impl<'c, J: std::marker::Send, M: std::marker::Send> PgQueueJob for PgTransactionJob<'c, J, M> {
    async fn complete(
        mut self,
    ) -> Result<CompletedJob, PgJobError<Box<PgTransactionJob<'c, J, M>>>> {
        let completed_job = self.job.complete();

        let base_query = format!(
            r#"
UPDATE
    "{0}"
SET
    finished_at = NOW(),
    status = 'completed'::job_status
WHERE
    "{0}".id = $2
    AND queue = $1
RETURNING
    "{0}".*
            "#,
            &self.table
        );

        sqlx::query(&base_query)
            .bind(&completed_job.queue)
            .bind(completed_job.id)
            .execute(&mut *self.transaction)
            .await
            .map_err(|error| PgJobError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        self.transaction
            .commit()
            .await
            .map_err(|error| PgJobError::TransactionError {
                command: "COMMIT".to_owned(),
                error,
            })?;

        Ok(completed_job)
    }

    async fn fail<E: serde::Serialize + std::marker::Sync + std::marker::Send>(
        mut self,
        error: E,
    ) -> Result<FailedJob<E>, PgJobError<Box<PgTransactionJob<'c, J, M>>>> {
        let failed_job = self.job.fail(error);

        let base_query = format!(
            r#"
UPDATE
    "{0}"
SET
    finished_at = NOW(),
    status = 'failed'::job_status
    errors = array_append("{0}".errors, $3)
WHERE
    "{0}".id = $2
    AND queue = $1
RETURNING
    "{0}".*
            "#,
            &self.table
        );

        sqlx::query(&base_query)
            .bind(&failed_job.queue)
            .bind(failed_job.id)
            .bind(&failed_job.error)
            .execute(&mut *self.transaction)
            .await
            .map_err(|error| PgJobError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        self.transaction
            .commit()
            .await
            .map_err(|error| PgJobError::TransactionError {
                command: "COMMIT".to_owned(),
                error,
            })?;

        Ok(failed_job)
    }

    async fn retry<E: serde::Serialize + std::marker::Sync + std::marker::Send>(
        mut self,
        error: E,
        preferred_retry_interval: Option<time::Duration>,
    ) -> Result<RetryableJob<E>, PgJobError<Box<PgTransactionJob<'c, J, M>>>> {
        if self.job.is_gte_max_attempts() {
            return Err(PgJobError::RetryInvalidError {
                job: Box::new(self),
                error: "Maximum attempts reached".to_owned(),
            });
        }
        let retryable_job = self.job.retry(error);

        let base_query = format!(
            r#"
UPDATE
    "{0}"
SET
    finished_at = NOW(),
    status = 'available'::job_status,
    scheduled_at = NOW() + $3,
    errors = array_append("{0}".errors, $4)
WHERE
    "{0}".id = $2
    AND queue = $1
RETURNING
    "{0}".*

            "#,
            &self.table
        );

        sqlx::query(&base_query)
            .bind(&retryable_job.queue)
            .bind(retryable_job.id)
            .bind(retry_interval)
            .bind(&retryable_job.error)
            .execute(&mut *self.transaction)
            .await
            .map_err(|error| PgJobError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        self.transaction
            .commit()
            .await
            .map_err(|error| PgJobError::TransactionError {
                command: "COMMIT".to_owned(),
                error,
            })?;

        Ok(retryable_job)
    }
}

/// A Job that has failed but can still be enqueued into a PgQueue to be retried at a later point.
/// The time until retry will depend on the PgQueue's RetryPolicy.
pub struct RetryableJob<J> {
    /// A unique id identifying a job.
    id: i64,
    /// A number corresponding to the current job attempt.
    pub attempt: i32,
    /// Any JSON-serializable value to be stored as an error.
    pub error: sqlx::types::Json<J>,
    /// A unique id identifying a job queue.
    pub queue: String,
}

/// A Job that has completed to be enqueued into a PgQueue and marked as completed.
pub struct CompletedJob {
    /// A unique id identifying a job.
    id: i64,
    /// A unique id identifying a job queue.
    pub queue: String,
}

/// A Job that has failed to be enqueued into a PgQueue and marked as failed.
pub struct FailedJob<J> {
    /// A unique id identifying a job.
    id: i64,
    /// Any JSON-serializable value to be stored as an error.
    pub error: sqlx::types::Json<J>,
    /// A unique id identifying a job queue.
    pub queue: String,
}

/// A NewJob to be enqueued into a PgQueue.
pub struct NewJob<J, M> {
    /// The maximum amount of attempts this NewJob has to complete.
    pub max_attempts: i32,
    /// The JSON-deserializable parameters for this NewJob.
    pub metadata: JobMetadata<M>,
    /// The JSON-deserializable parameters for this NewJob.
    pub parameters: JobParameters<J>,
    /// The target of the NewJob. E.g. an endpoint or service we are trying to reach.
    pub target: String,
}

impl<J, M> NewJob<J, M> {
    pub fn new(max_attempts: i32, metadata: M, parameters: J, target: &str) -> Self {
        Self {
            max_attempts,
            metadata: sqlx::types::Json(metadata),
            parameters: sqlx::types::Json(parameters),
            target: target.to_owned(),
        }
    }
}

/// A queue implemented on top of a PostgreSQL table.
#[derive(Clone)]
pub struct PgQueue {
    /// A name to identify this PgQueue as multiple may share a table.
    name: String,
    /// A connection pool used to connect to the PostgreSQL database.
    pool: PgPool,
    /// The identifier of the PostgreSQL table this queue runs on.
    table: String,
}

pub type PgQueueResult<T> = std::result::Result<T, PgQueueError>;

impl PgQueue {
    /// Initialize a new PgQueue backed by table in PostgreSQL.
    ///
    /// # Arguments
    ///
    /// * `queue_name`: A name for the queue we are going to initialize.
    /// * `table_name`: The name for the table the queue will use in PostgreSQL.
    /// * `url`: A URL pointing to where the PostgreSQL database is hosted.
    /// * `worker_name`: The name of the worker that is operating with this queue.
    pub async fn new(queue_name: &str, table_name: &str, url: &str) -> PgQueueResult<Self> {
        let name = queue_name.to_owned();
        let table = table_name.to_owned();
        let pool = PgPoolOptions::new()
            .connect_lazy(url)
            .map_err(|error| PgQueueError::PoolCreationError { error })?;

        Ok(Self { name, pool, table })
    }

    /// Dequeue a Job from this PgQueue to work on it.
    pub async fn dequeue<
        J: for<'d> serde::Deserialize<'d> + std::marker::Send + std::marker::Unpin + 'static,
        M: for<'d> serde::Deserialize<'d> + std::marker::Send + std::marker::Unpin + 'static,
    >(
        &self,
        attempted_by: &str,
    ) -> PgQueueResult<Option<PgJob<J, M>>> {
        let mut connection = self
            .pool
            .acquire()
            .await
            .map_err(|error| PgQueueError::ConnectionError { error })?;

        // The query that follows uses a FOR UPDATE SKIP LOCKED clause.
        // For more details on this see: 2ndquadrant.com/en/blog/what-is-select-skip-locked-for-in-postgresql-9-5.
        let base_query = format!(
            r#"
WITH available_in_queue AS (
    SELECT
        id
    FROM
        "{0}"
    WHERE
        status = 'available'
        AND scheduled_at <= NOW()
        AND queue = $1
    ORDER BY
        id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE
    "{0}"
SET
    attempted_at = NOW(),
    status = 'running'::job_status,
    attempt = "{0}".attempt + 1,
    attempted_by = array_append("{0}".attempted_by, $2::text)
FROM
    available_in_queue
WHERE
    "{0}".id = available_in_queue.id
RETURNING
    "{0}".*
            "#,
            &self.table
        );

        let query_result: Result<Job<J, M>, sqlx::Error> = sqlx::query_as(&base_query)
            .bind(&self.name)
            .bind(attempted_by)
            .fetch_one(&mut *connection)
            .await;

        match query_result {
            Ok(job) => Ok(Some(PgJob {
                job,
                table: self.table.to_owned(),
                connection,
            })),

            // Although connection would be closed once it goes out of scope, sqlx recommends explicitly calling close().
            // See: https://docs.rs/sqlx/latest/sqlx/postgres/any/trait.AnyConnectionBackend.html#tymethod.close.
            Err(sqlx::Error::RowNotFound) => {
                let _ = connection.close().await;
                Ok(None)
            }
            Err(e) => {
                let _ = connection.close().await;
                Err(PgQueueError::QueryError {
                    command: "UPDATE".to_owned(),
                    error: e,
                })
            }
        }
    }

    /// Dequeue a Job from this PgQueue to work on it.
    pub async fn dequeue_tx<
        'a,
        J: for<'d> serde::Deserialize<'d> + std::marker::Send + std::marker::Unpin + 'static,
        M: for<'d> serde::Deserialize<'d> + std::marker::Send + std::marker::Unpin + 'static,
    >(
        &self,
        attempted_by: &str,
    ) -> PgQueueResult<Option<PgTransactionJob<'a, J, M>>> {
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|error| PgQueueError::ConnectionError { error })?;

        // The query that follows uses a FOR UPDATE SKIP LOCKED clause.
        // For more details on this see: 2ndquadrant.com/en/blog/what-is-select-skip-locked-for-in-postgresql-9-5.
        let base_query = format!(
            r#"
WITH available_in_queue AS (
    SELECT
        id
    FROM
        "{0}"
    WHERE
        status = 'available'
        AND scheduled_at <= NOW()
        AND queue = $1
    ORDER BY
        id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE
    "{0}"
SET
    attempted_at = NOW(),
    status = 'running'::job_status,
    attempt = "{0}".attempt + 1,
    attempted_by = array_append("{0}".attempted_by, $2::text)
FROM
    available_in_queue
WHERE
    "{0}".id = available_in_queue.id
RETURNING
    "{0}".*
            "#,
            &self.table
        );

        let query_result: Result<Job<J, M>, sqlx::Error> = sqlx::query_as(&base_query)
            .bind(&self.name)
            .bind(attempted_by)
            .fetch_one(&mut *tx)
            .await;

        match query_result {
            Ok(job) => Ok(Some(PgTransactionJob {
                job,
                table: self.table.to_owned(),
                transaction: tx,
            })),

            // Transaction is rolledback on drop.
            Err(sqlx::Error::RowNotFound) => Ok(None),
            Err(e) => Err(PgQueueError::QueryError {
                command: "UPDATE".to_owned(),
                error: e,
            }),
        }
    }

    /// Enqueue a Job into this PgQueue.
    /// We take ownership of NewJob to enforce a specific NewJob is only enqueued once.
    pub async fn enqueue<
        J: serde::Serialize + std::marker::Sync,
        M: serde::Serialize + std::marker::Sync,
    >(
        &self,
        job: NewJob<J, M>,
    ) -> PgQueueResult<()> {
        // TODO: Escaping. I think sqlx doesn't support identifiers.
        let base_query = format!(
            r#"
INSERT INTO {}
    (attempt, created_at, scheduled_at, max_attempts, metadata, parameters, queue, status, target)
VALUES
    (0, NOW(), NOW(), $1, $2, $3, $4, 'available'::job_status, $5)
            "#,
            &self.table
        );

        sqlx::query(&base_query)
            .bind(job.max_attempts)
            .bind(&job.metadata)
            .bind(&job.parameters)
            .bind(&self.name)
            .bind(&job.target)
            .execute(&self.pool)
            .await
            .map_err(|error| PgQueueError::QueryError {
                command: "INSERT".to_owned(),
                error,
            })?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::retry::RetryPolicy;

    #[derive(serde::Serialize, serde::Deserialize, PartialEq, Debug)]
    struct JobMetadata {
        team_id: u32,
        plugin_config_id: u32,
        plugin_id: u32,
    }

    impl Default for JobMetadata {
        fn default() -> Self {
            Self {
                team_id: 0,
                plugin_config_id: 1,
                plugin_id: 2,
            }
        }
    }

    #[derive(serde::Serialize, serde::Deserialize, PartialEq, Debug)]
    struct JobParameters {
        method: String,
        body: String,
        url: String,
    }

    impl Default for JobParameters {
        fn default() -> Self {
            Self {
                method: "POST".to_string(),
                body: "{\"event\":\"event-name\"}".to_string(),
                url: "https://localhost".to_string(),
            }
        }
    }

    /// Use process id as a worker id for tests.
    fn worker_id() -> String {
        std::process::id().to_string()
    }

    /// Hardcoded test value for job target.
    fn job_target() -> String {
        "https://myhost/endpoint".to_owned()
    }

    #[tokio::test]
    async fn test_can_dequeue_job() {
        let job_target = job_target();
        let job_parameters = JobParameters::default();
        let job_metadata = JobMetadata::default();
        let worker_id = worker_id();
        let new_job = NewJob::new(1, job_metadata, job_parameters, &job_target);

        let queue = PgQueue::new(
            "test_can_dequeue_job",
            "job_queue",
            "postgres://posthog:posthog@localhost:15432/test_database",
        )
        .await
        .expect("failed to connect to local test postgresql database");

        queue.enqueue(new_job).await.expect("failed to enqueue job");

        let pg_job: PgJob<JobParameters, JobMetadata> = queue
            .dequeue(&worker_id)
            .await
            .expect("failed to dequeue job")
            .expect("didn't find a job to dequeue");

        assert_eq!(pg_job.job.attempt, 1);
        assert!(pg_job.job.attempted_by.contains(&worker_id));
        assert_eq!(pg_job.job.attempted_by.len(), 1);
        assert_eq!(pg_job.job.max_attempts, 1);
        assert_eq!(*pg_job.job.parameters.as_ref(), JobParameters::default());
        assert_eq!(pg_job.job.status, JobStatus::Running);
        assert_eq!(pg_job.job.target, job_target);
    }

    #[tokio::test]
    async fn test_dequeue_returns_none_on_no_jobs() {
        let worker_id = worker_id();
        let queue = PgQueue::new(
            "test_dequeue_returns_none_on_no_jobs",
            "job_queue",
            "postgres://posthog:posthog@localhost:15432/test_database",
        )
        .await
        .expect("failed to connect to local test postgresql database");

        let pg_job: Option<PgJob<JobParameters, JobMetadata>> = queue
            .dequeue(&worker_id)
            .await
            .expect("failed to dequeue job");

        assert!(pg_job.is_none());
    }

    #[tokio::test]
    async fn test_can_dequeue_tx_job() {
        let job_target = job_target();
        let job_metadata = JobMetadata::default();
        let job_parameters = JobParameters::default();
        let worker_id = worker_id();
        let new_job = NewJob::new(1, job_metadata, job_parameters, &job_target);

        let queue = PgQueue::new(
            "test_can_dequeue_tx_job",
            "job_queue",
            "postgres://posthog:posthog@localhost:15432/test_database",
        )
        .await
        .expect("failed to connect to local test postgresql database");

        queue.enqueue(new_job).await.expect("failed to enqueue job");

        let tx_job: PgTransactionJob<'_, JobParameters, JobMetadata> = queue
            .dequeue_tx(&worker_id)
            .await
            .expect("failed to dequeue job")
            .expect("didn't find a job to dequeue");

        assert_eq!(tx_job.job.attempt, 1);
        assert!(tx_job.job.attempted_by.contains(&worker_id));
        assert_eq!(tx_job.job.attempted_by.len(), 1);
        assert_eq!(tx_job.job.max_attempts, 1);
        assert_eq!(*tx_job.job.metadata.as_ref(), JobMetadata::default());
        assert_eq!(*tx_job.job.parameters.as_ref(), JobParameters::default());
        assert_eq!(tx_job.job.status, JobStatus::Running);
        assert_eq!(tx_job.job.target, job_target);
    }

    #[tokio::test]
    async fn test_dequeue_tx_returns_none_on_no_jobs() {
        let worker_id = worker_id();
        let queue = PgQueue::new(
            "test_dequeue_tx_returns_none_on_no_jobs",
            "job_queue",
            "postgres://posthog:posthog@localhost:15432/test_database",
        )
        .await
        .expect("failed to connect to local test postgresql database");

        let tx_job: Option<PgTransactionJob<'_, JobParameters, JobMetadata>> = queue
            .dequeue_tx(&worker_id)
            .await
            .expect("failed to dequeue job");

        assert!(tx_job.is_none());
    }

    #[tokio::test]
    async fn test_can_retry_job_with_remaining_attempts() {
        let job_target = job_target();
        let job_parameters = JobParameters::default();
        let job_metadata = JobMetadata::default();
        let worker_id = worker_id();
        let new_job = NewJob::new(2, job_metadata, job_parameters, &job_target);
        let retry_policy = RetryPolicy {
            backoff_coefficient: 0,
            initial_interval: time::Duration::from_secs(0),
            maximum_interval: None,
        };

        let queue = PgQueue::new(
            "test_can_retry_job_with_remaining_attempts",
            "job_queue",
            "postgres://posthog:posthog@localhost:15432/test_database",
        )
        .await
        .expect("failed to connect to local test postgresql database");

        queue.enqueue(new_job).await.expect("failed to enqueue job");
        let job: PgJob<JobParameters, JobMetadata> = queue
            .dequeue(&worker_id)
            .await
            .expect("failed to dequeue job")
            .expect("didn't find a job to dequeue");
        let retry_interval = retry_policy.time_until_next_retry(job.job.attempt as u32, None);
        let _ = job
            .retry("a very reasonable failure reason", retry_interval)
            .await
            .expect("failed to retry job");
        let retried_job: PgJob<JobParameters, JobMetadata> = queue
            .dequeue(&worker_id)
            .await
            .expect("failed to dequeue job")
            .expect("didn't find retried job to dequeue");

        assert_eq!(retried_job.job.attempt, 2);
        assert!(retried_job.job.attempted_by.contains(&worker_id));
        assert_eq!(retried_job.job.attempted_by.len(), 2);
        assert_eq!(retried_job.job.max_attempts, 2);
        assert_eq!(
            *retried_job.job.parameters.as_ref(),
            JobParameters::default()
        );
        assert_eq!(retried_job.job.status, JobStatus::Running);
        assert_eq!(retried_job.job.target, job_target);
    }

    #[tokio::test]
    #[should_panic(expected = "failed to retry job")]
    async fn test_cannot_retry_job_without_remaining_attempts() {
        let job_target = job_target();
        let job_parameters = JobParameters::default();
        let job_metadata = JobMetadata::default();
        let worker_id = worker_id();
        let new_job = NewJob::new(1, job_metadata, job_parameters, &job_target);
        let retry_policy = RetryPolicy {
            backoff_coefficient: 0,
            initial_interval: time::Duration::from_secs(0),
            maximum_interval: None,
        };

        let queue = PgQueue::new(
            "test_cannot_retry_job_without_remaining_attempts",
            "job_queue",
            "postgres://posthog:posthog@localhost:15432/test_database",
        )
        .await
        .expect("failed to connect to local test postgresql database");

        queue.enqueue(new_job).await.expect("failed to enqueue job");

        let job: PgJob<JobParameters, JobMetadata> = queue
            .dequeue(&worker_id)
            .await
            .expect("failed to dequeue job")
            .expect("didn't find a job to dequeue");
        let retry_interval = retry_policy.time_until_next_retry(job.job.attempt as u32, None);
        job.retry("a very reasonable failure reason", retry_interval)
            .await
            .expect("failed to retry job");
    }
}
