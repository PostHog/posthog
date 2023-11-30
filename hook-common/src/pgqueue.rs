//! # PgQueue
//!
//! A job queue implementation backed by a PostgreSQL table.

use std::str::FromStr;

use chrono::prelude::*;
use serde::{de::DeserializeOwned, Serialize};
use sqlx::postgres::{PgPool, PgPoolOptions};
use thiserror::Error;

/// Enumeration of errors for operations with PgQueue.
/// Errors that can originate from sqlx and are wrapped by us to provide additional context.
#[derive(Error, Debug)]
pub enum PgQueueError {
    #[error("connection failed with: {error}")]
    ConnectionError {
        error: sqlx::Error
    },
    #[error("{command} query failed with: {error}")]
    QueryError {
        command: String,
        error: sqlx::Error
    },
    #[error("{0} is not a valid JobStatus")]
    ParseJobStatusError(String),
}

/// Enumeration of possible statuses for a Job.
#[derive(Debug, PartialEq, sqlx::Type)]
#[sqlx(type_name = "job_status")]
#[sqlx(rename_all = "lowercase")]
pub enum JobStatus {
    /// A job that is waiting in the queue to be picked up by a worker.
    Available,
    /// A job that was successfully completed by a worker.
    Completed,
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
    /// A datetime corresponding to when the current job attempt started.
    pub attempted_at: Option<DateTime<Utc>>,
    /// A vector of identifiers that have attempted this job. E.g. thread ids, pod names, etc...
    pub attempted_by: Vec<String>,
    /// A datetime corresponding to when the job was finished (either successfully or unsuccessfully).
    pub finished_at: Option<DateTime<Utc>>,
    /// A datetime corresponding to when the job was created.
    pub created_at: DateTime<Utc>,
    /// A datetime corresponding to when the first job attempt was started.
    pub started_at: Option<DateTime<Utc>>,
    /// The current status of the job.
    pub status: JobStatus,
    /// Arbitrary job parameters stored as JSON.
    pub parameters: sqlx::types::Json<J>,
}

/// A NewJob to be enqueued into a PgQueue.
pub struct NewJob<J> {
    pub attempt: i32,
    pub finished_at: Option<DateTime<Utc>>,
    pub started_at: Option<DateTime<Utc>>,
    pub status: JobStatus,
    pub parameters: sqlx::types::Json<J>,
}

impl<J> NewJob<J> {
    pub fn new(parameters: J) -> Self {
        Self {
            attempt: 0,
            parameters:  sqlx::types::Json(parameters),
            finished_at: None,
            started_at: None,
            status: JobStatus::Available,
        }
    }
}

/// A queue implemented on top of a PostgreSQL table.
pub struct PgQueue {
    /// The identifier of the PostgreSQL table this queue runs on.
    table: String,
    /// A connection pool used to connect to the PostgreSQL database.
    pool: PgPool,
    /// The identifier of the worker listening on this queue.
    worker: String,
}

pub type PgQueueResult<T> = std::result::Result<T, PgQueueError>;

impl PgQueue {
    /// Initialize a new PgQueue backed by table in PostgreSQL.
    pub async fn new(table: &str, url: &str, worker: &str) -> PgQueueResult<Self> {
        let table = table.to_owned();
        let worker = worker.to_owned();
        let pool = PgPoolOptions::new()
            .connect(url)
            .await
            .map_err(|error| PgQueueError::ConnectionError {error})?;

        Ok(Self {
            table,
            pool,
            worker,
        })
    }

    /// Dequeue a Job from this PgQueue.
    pub async fn dequeue<J: DeserializeOwned + std::marker::Send + std::marker::Unpin + 'static>(&self) -> PgQueueResult<Job<J>> {
        let base_query = format!(
            r#"
WITH available_in_queue AS (
    SELECT
        id
    FROM
        "{0}"
    WHERE
        status = 'available'
    ORDER BY
        id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE
    "{0}"
SET
    started_at = NOW(),
    status = 'running'::job_status,
    attempt = "{0}".attempt + 1,
    attempted_by = array_append("{0}".attempted_by, $1::text)
FROM
    available_in_queue
WHERE
    "{0}".id = available_in_queue.id
RETURNING
    "{0}".*
            "#, &self.table);

        let item: Job<J> = sqlx::query_as(&base_query)
            .bind(&self.worker)
            .fetch_one(&self.pool)
            .await
            .map_err(|error| PgQueueError::QueryError { command: "UPDATE".to_owned(), error})?;

        Ok(item)
    }

    /// Enqueue a Job into this PgQueue.
    /// We take ownership of NewJob to enforce a specific NewJob is only enqueued once.
    pub async fn enqueue<J: Serialize + std::marker::Sync>(&self, job: NewJob<J>) -> PgQueueResult<()> {
        // TODO: Escaping. I think sqlx doesn't support identifiers.
        let base_query = format!(
            r#"
INSERT INTO {}
    (attempt, created_at, finished_at, started_at, status, parameters)
VALUES
    ($1, NOW(), $2, $3, $4::job_status, $5)
            "#, &self.table);

        sqlx::query(&base_query)
            .bind(job.attempt)
            .bind(job.finished_at)
            .bind(job.started_at)
            .bind(job.status)
            .bind(&job.parameters)
            .execute(&self.pool)
            .await
            .map_err(|error| PgQueueError::QueryError { command: "INSERT".to_owned(), error})?;

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
    async fn test_can_enqueue_and_dequeue_job() {
        let job_parameters = JobParameters {
            method: "POST".to_string(),
            body: "{\"event\":\"event-name\"}".to_string(),
            url: "https://localhost".to_string(),
        };
        let new_job = NewJob::new(job_parameters);

        let worker_id = std::process::id().to_string();
        let queue = PgQueue::new("job_queue", "postgres://posthog:posthog@localhost:15432/test_database", &worker_id)
            .await
            .expect("failed to connect to local test postgresql database");

        queue.enqueue(new_job).await.expect("failed to enqueue job");

        let job: Job<JobParameters> = queue.dequeue().await.expect("failed to dequeue job");

        assert_eq!(job.attempt, 1);
        assert_eq!(job.parameters.method, "POST".to_string());
        assert_eq!(job.parameters.body, "{\"event\":\"event-name\"}".to_string());
        assert_eq!(job.parameters.url, "https://localhost".to_string());
        assert!(job.finished_at.is_none());
        assert_eq!(job.status, JobStatus::Running);
        assert!(job.attempted_by.contains(&worker_id));
    }
}
