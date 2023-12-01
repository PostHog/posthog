//! # PgQueue
//!
//! A job queue implementation backed by a PostgreSQL table.

use std::default::Default;
use std::str::FromStr;

use chrono::{prelude::*, Duration};
use serde::{de::DeserializeOwned, Serialize};
use sqlx::postgres::{PgPool, PgPoolOptions};
use thiserror::Error;

/// Enumeration of errors for operations with PgQueue.
/// Errors that can originate from sqlx and are wrapped by us to provide additional context.
#[derive(Error, Debug)]
pub enum PgQueueError {
    #[error("connection failed with: {error}")]
    ConnectionError { error: sqlx::Error },
    #[error("{command} query failed with: {error}")]
    QueryError { command: String, error: sqlx::Error },
    #[error("{0} is not a valid JobStatus")]
    ParseJobStatusError(String),
    #[error("{0} Job has reached max attempts and cannot be retried further")]
    MaxAttemptsReachedError(String),
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

/// A Job to be executed by a worker dequeueing a PgQueue.
#[derive(sqlx::FromRow)]
pub struct Job<J> {
    /// A unique id identifying a job.
    pub id: i64,
    /// A number corresponding to the current job attempt.
    pub attempt: i32,
    /// A datetime corresponding to when the job was attempted.
    pub attempted_at: DateTime<Utc>,
    /// A vector of identifiers that have attempted this job. E.g. thread ids, pod names, etc...
    pub attempted_by: Vec<String>,
    /// A datetime corresponding to when the job was created.
    pub created_at: DateTime<Utc>,
    /// The current job's number of max attempts.
    pub max_attempts: i32,
    /// Arbitrary job parameters stored as JSON.
    pub parameters: JobParameters<J>,
    /// The current status of the job.
    pub status: JobStatus,
    /// The target of the job. E.g. an endpoint or service we are trying to reach.
    pub target: String,
}

impl<J> Job<J> {
    /// Consume Job to retry it.
    /// This returns a RetryableJob that can be enqueued by PgQueue.
    ///
    /// # Arguments
    ///
    /// * `error`: Any JSON-serializable value to be stored as an error.
    pub fn retry<E: Serialize>(self, error: E) -> Result<RetryableJob<E>, PgQueueError> {
        if self.attempt >= self.max_attempts {
            Err(PgQueueError::MaxAttemptsReachedError(self.target))
        } else {
            Ok(RetryableJob {
                id: self.id,
                attempt: self.attempt,
                error: sqlx::types::Json(error),
            })
        }
    }

    /// Consume Job to complete it.
    /// This returns a CompletedJob that can be enqueued by PgQueue.
    pub fn complete(self) -> CompletedJob {
        CompletedJob { id: self.id }
    }

    /// Consume Job to fail it.
    /// This returns a FailedJob that can be enqueued by PgQueue.
    ///
    /// # Arguments
    ///
    /// * `error`: Any JSON-serializable value to be stored as an error.
    pub fn fail<E: Serialize>(self, error: E) -> FailedJob<E> {
        FailedJob {
            id: self.id,
            error: sqlx::types::Json(error),
        }
    }
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            backoff_coefficient: 2,
            initial_interval: Duration::seconds(1),
            maximum_interval: None,
        }
    }
}

/// A Job that has failed but can still be enqueued into a PgQueue to be retried at a later point.
/// The time until retry will depend on the PgQueue's RetryPolicy.
pub struct RetryableJob<J> {
    /// A unique id identifying a job.
    pub id: i64,
    /// A number corresponding to the current job attempt.
    pub attempt: i32,
    /// Any JSON-serializable value to be stored as an error.
    pub error: sqlx::types::Json<J>,
}

/// A Job that has completed to be enqueued into a PgQueue and marked as completed.
pub struct CompletedJob {
    /// A unique id identifying a job.
    pub id: i64,
}

/// A Job that has failed to be enqueued into a PgQueue and marked as failed.
pub struct FailedJob<J> {
    /// A unique id identifying a job.
    pub id: i64,
    /// Any JSON-serializable value to be stored as an error.
    pub error: sqlx::types::Json<J>,
}

/// A NewJob to be enqueued into a PgQueue.
pub struct NewJob<J> {
    /// The maximum amount of attempts this NewJob has to complete.
    pub max_attempts: i32,
    /// The JSON-deserializable parameters for this NewJob.
    pub parameters: JobParameters<J>,
    /// The target of the NewJob. E.g. an endpoint or service we are trying to reach.
    pub target: String,
}

impl<J> NewJob<J> {
    pub fn new(max_attempts: i32, parameters: J, target: &str) -> Self {
        Self {
            max_attempts,
            parameters: sqlx::types::Json(parameters),
            target: target.to_owned(),
        }
    }
}

/// The retry policy that PgQueue will use to determine how to set scheduled_at when enqueuing a retry.
pub struct RetryPolicy {
    /// Coeficient to multiply initial_interval with for every past attempt.
    backoff_coefficient: i32,
    /// The backoff interval for the first retry.
    initial_interval: Duration,
    /// The maximum possible backoff between retries.
    maximum_interval: Option<Duration>,
}

impl RetryPolicy {
    /// Calculate the time until the next retry for a given RetryableJob.
    pub fn time_until_next_retry<J>(&self, job: &RetryableJob<J>) -> Duration {
        let candidate_interval =
            self.initial_interval * self.backoff_coefficient.pow(job.attempt as u32);

        if let Some(max_interval) = self.maximum_interval {
            std::cmp::min(candidate_interval, max_interval)
        } else {
            candidate_interval
        }
    }
}

/// A queue implemented on top of a PostgreSQL table.
pub struct PgQueue {
    /// A name to identify this PgQueue as multiple may share a table.
    name: String,
    /// A connection pool used to connect to the PostgreSQL database.
    pool: PgPool,
    /// The retry policy to use to enqueue any retryable jobs.
    retry_policy: RetryPolicy,
    /// The identifier of the PostgreSQL table this queue runs on.
    table: String,
    /// The identifier of the worker listening on this queue.
    worker: String,
}

pub type PgQueueResult<T> = std::result::Result<T, PgQueueError>;

impl PgQueue {
    /// Initialize a new PgQueue backed by table in PostgreSQL.
    pub async fn new(
        name: &str,
        table: &str,
        retry_policy: RetryPolicy,
        url: &str,
        worker: &str,
    ) -> PgQueueResult<Self> {
        let name = name.to_owned();
        let table = table.to_owned();
        let worker = worker.to_owned();
        let pool = PgPoolOptions::new()
            .connect(url)
            .await
            .map_err(|error| PgQueueError::ConnectionError { error })?;

        Ok(Self {
            name,
            table,
            pool,
            worker,
            retry_policy,
        })
    }

    /// Dequeue a Job from this PgQueue to work on it.
    pub async fn dequeue<J: DeserializeOwned + std::marker::Send + std::marker::Unpin + 'static>(
        &self,
    ) -> PgQueueResult<Job<J>> {
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

        let item: Job<J> = sqlx::query_as(&base_query)
            .bind(&self.name)
            .bind(&self.worker)
            .fetch_one(&self.pool)
            .await
            .map_err(|error| PgQueueError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        Ok(item)
    }

    /// Enqueue a Job into this PgQueue.
    /// We take ownership of NewJob to enforce a specific NewJob is only enqueued once.
    pub async fn enqueue<J: Serialize + std::marker::Sync>(
        &self,
        job: NewJob<J>,
    ) -> PgQueueResult<()> {
        // TODO: Escaping. I think sqlx doesn't support identifiers.
        let base_query = format!(
            r#"
INSERT INTO {}
    (attempt, created_at, scheduled_at, max_attempts, parameters, queue, status, target)
VALUES
    (0, NOW(), NOW(), $1, $2, $3, 'available'::job_status, $4)
            "#,
            &self.table
        );

        sqlx::query(&base_query)
            .bind(job.max_attempts)
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

    /// Enqueue a Job back into this PgQueue marked as completed.
    /// We take ownership of Job to enforce a specific Job is only enqueued once.
    pub async fn enqueue_completed(&self, job: CompletedJob) -> PgQueueResult<()> {
        // TODO: Escaping. I think sqlx doesn't support identifiers.
        let base_query = format!(
            r#"
UPDATE
    "{0}"
SET
    finished_at = NOW(),
    completed_at = NOW(),
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
            .bind(&self.name)
            .bind(job.id)
            .execute(&self.pool)
            .await
            .map_err(|error| PgQueueError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        Ok(())
    }

    /// Enqueue a Job back into this PgQueue to be retried at a later time.
    /// We take ownership of Job to enforce a specific Job is only enqueued once.
    pub async fn enqueue_retryable<J: Serialize + std::marker::Sync>(
        &self,
        job: RetryableJob<J>,
    ) -> PgQueueResult<()> {
        // TODO: Escaping. I think sqlx doesn't support identifiers.
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
            .bind(&self.name)
            .bind(job.id)
            .bind(self.retry_policy.time_until_next_retry(&job))
            .bind(&job.error)
            .execute(&self.pool)
            .await
            .map_err(|error| PgQueueError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        Ok(())
    }

    /// Enqueue a Job back into this PgQueue marked as failed.
    /// Jobs marked as failed will remain in the queue for tracking purposes but will not be dequeued.
    /// We take ownership of FailedJob to enforce a specific FailedJob is only enqueued once.
    pub async fn enqueue_failed<J: Serialize + std::marker::Sync>(
        &self,
        job: FailedJob<J>,
    ) -> PgQueueResult<()> {
        // TODO: Escaping. I think sqlx doesn't support identifiers.
        let base_query = format!(
            r#"
UPDATE
    "{0}"
SET
    finished_at = NOW(),
    completed_at = NOW(),
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
            .bind(&self.name)
            .bind(job.id)
            .bind(&job.error)
            .execute(&self.pool)
            .await
            .map_err(|error| PgQueueError::QueryError {
                command: "UPDATE".to_owned(),
                error,
            })?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[derive(Serialize, Deserialize)]
    struct JobParameters {
        method: String,
        body: String,
        url: String,
    }

    #[tokio::test]
    async fn test_can_dequeue_job() {
        let job_parameters = JobParameters {
            method: "POST".to_string(),
            body: "{\"event\":\"event-name\"}".to_string(),
            url: "https://localhost".to_string(),
        };
        let job_target = "https://myhost/endpoint";
        let new_job = NewJob::new(1, job_parameters, job_target);

        let worker_id = std::process::id().to_string();
        let retry_policy = RetryPolicy::default();
        let queue = PgQueue::new(
            "test_queue_1",
            "job_queue",
            retry_policy,
            "postgres://posthog:posthog@localhost:15432/test_database",
            &worker_id,
        )
        .await
        .expect("failed to connect to local test postgresql database");

        queue.enqueue(new_job).await.expect("failed to enqueue job");

        let job: Job<JobParameters> = queue.dequeue().await.expect("failed to dequeue job");

        assert_eq!(job.attempt, 1);
        assert!(job.attempted_by.contains(&worker_id));
        assert_eq!(job.attempted_by.len(), 1);
        assert_eq!(job.max_attempts, 1);
        assert_eq!(job.parameters.method, "POST".to_string());
        assert_eq!(
            job.parameters.body,
            "{\"event\":\"event-name\"}".to_string()
        );
        assert_eq!(job.parameters.url, "https://localhost".to_string());
        assert_eq!(job.status, JobStatus::Running);
        assert_eq!(job.target, job_target.to_string());
    }

    #[tokio::test]
    async fn test_can_retry_job_with_remaining_attempts() {
        let job_parameters = JobParameters {
            method: "POST".to_string(),
            body: "{\"event\":\"event-name\"}".to_string(),
            url: "https://localhost".to_string(),
        };
        let job_target = "https://myhost/endpoint";
        let new_job = NewJob::new(2, job_parameters, job_target);

        let worker_id = std::process::id().to_string();
        let retry_policy = RetryPolicy {
            backoff_coefficient: 0,
            initial_interval: Duration::seconds(0),
            maximum_interval: None,
        };
        let queue = PgQueue::new(
            "test_queue_2",
            "job_queue",
            retry_policy,
            "postgres://posthog:posthog@localhost:15432/test_database",
            &worker_id,
        )
        .await
        .expect("failed to connect to local test postgresql database");

        queue.enqueue(new_job).await.expect("failed to enqueue job");
        let job: Job<JobParameters> = queue.dequeue().await.expect("failed to dequeue job");
        let retryable_job = job
            .retry("a very reasonable failure reason")
            .expect("failed to retry job");

        queue
            .enqueue_retryable(retryable_job)
            .await
            .expect("failed to enqueue retryable job");
        let retried_job: Job<JobParameters> = queue.dequeue().await.expect("failed to dequeue job");

        assert_eq!(retried_job.attempt, 2);
        assert!(retried_job.attempted_by.contains(&worker_id));
        assert_eq!(retried_job.attempted_by.len(), 2);
        assert_eq!(retried_job.max_attempts, 2);
        assert_eq!(retried_job.parameters.method, "POST".to_string());
        assert_eq!(
            retried_job.parameters.body,
            "{\"event\":\"event-name\"}".to_string()
        );
        assert_eq!(retried_job.parameters.url, "https://localhost".to_string());
        assert_eq!(retried_job.status, JobStatus::Running);
        assert_eq!(retried_job.target, job_target.to_string());
    }

    #[tokio::test]
    #[should_panic(expected = "failed to retry job")]
    async fn test_cannot_retry_job_without_remaining_attempts() {
        let job_parameters = JobParameters {
            method: "POST".to_string(),
            body: "{\"event\":\"event-name\"}".to_string(),
            url: "https://localhost".to_string(),
        };
        let job_target = "https://myhost/endpoint";
        let new_job = NewJob::new(1, job_parameters, job_target);

        let worker_id = std::process::id().to_string();
        let retry_policy = RetryPolicy {
            backoff_coefficient: 0,
            initial_interval: Duration::seconds(0),
            maximum_interval: None,
        };
        let queue = PgQueue::new(
            "test_queue_3",
            "job_queue",
            retry_policy,
            "postgres://posthog:posthog@localhost:15432/test_database",
            &worker_id,
        )
        .await
        .expect("failed to connect to local test postgresql database");

        queue.enqueue(new_job).await.expect("failed to enqueue job");
        let job: Job<JobParameters> = queue.dequeue().await.expect("failed to dequeue job");
        job.retry("a very reasonable failure reason")
            .expect("failed to retry job");
    }
}
