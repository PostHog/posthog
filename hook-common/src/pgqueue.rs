use std::str::FromStr;

use chrono::prelude::*;
use serde::{de::DeserializeOwned, Serialize};
use sqlx::postgres::{PgPool, PgPoolOptions};
use thiserror::Error;

/// Enumeration of errors for operations with PgQueue.
/// Errors can originate from sqlx and are wrapped by us to provide additional context.
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
/// Available: A job that is waiting in the queue to be picked up by a worker.
/// Completed: A job that was successfully completed by a worker.
/// Failed: A job that was unsuccessfully completed by a worker.
/// Running: A job that was picked up by a worker and it's currentlly being run.
#[derive(Debug, PartialEq, sqlx::Type)]
#[sqlx(type_name = "job_status")]
#[sqlx(rename_all = "lowercase")]
pub enum JobStatus {
    Available,
    Completed,
    Failed,
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
    pub id: i64,
    pub attempt: i32,
    pub finished_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub started_at: Option<DateTime<Utc>>,
    pub status: JobStatus,
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
    table: String,
    pool: PgPool,
}

pub type PgQueueResult<T> = std::result::Result<T, PgQueueError>;

impl PgQueue {
    /// Initialize a new PgQueue backed by table in PostgreSQL.
    pub async fn new(table: &str, url: &str) -> PgQueueResult<Self> {
        let table = table.to_owned();
        let pool = PgPoolOptions::new()
            .connect(url)
            .await
            .map_err(|error| PgQueueError::ConnectionError {error})?;

        Ok(Self {
            table,
            pool,
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
    attempt = "{0}".attempt + 1
FROM
    available_in_queue
WHERE
    "{0}".id = available_in_queue.id
RETURNING
    "{0}".*
            "#, &self.table);

        let item: Job<J> = sqlx::query_as(&base_query)
            .bind(&self.table)
            .bind(&self.table)
            .bind(&self.table)
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

        let queue = PgQueue::new("job_queue", "postgres://posthog:posthog@localhost:15432/test_database").await.unwrap();

        queue.enqueue(new_job).await.unwrap();

        let job: Job<JobParameters> = queue.dequeue().await.unwrap();

        assert_eq!(job.attempt, 1);
        assert_eq!(job.parameters.method, "POST".to_string());
        assert_eq!(job.parameters.body, "{\"event\":\"event-name\"}".to_string());
        assert_eq!(job.parameters.url, "https://localhost".to_string());
        assert_eq!(job.finished_at, None);
        assert_eq!(job.status, JobStatus::Running);
    }
}
