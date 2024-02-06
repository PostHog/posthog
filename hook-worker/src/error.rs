use std::time;

use hook_common::pgqueue;
use thiserror::Error;

/// Enumeration of errors related to webhook job processing in the WebhookWorker.
#[derive(Error, Debug)]
pub enum WebhookError {
    #[error("{0} is not a valid HttpMethod")]
    ParseHttpMethodError(String),
    #[error("error parsing webhook headers")]
    ParseHeadersError(http::Error),
    #[error("error parsing webhook url")]
    ParseUrlError(url::ParseError),
    #[error("a webhook could not be delivered but it could be retried later: {error}")]
    RetryableRequestError {
        error: reqwest::Error,
        retry_after: Option<time::Duration>,
    },
    #[error("a webhook could not be delivered and it cannot be retried further: {0}")]
    NonRetryableRetryableRequestError(reqwest::Error),
}

/// Enumeration of errors related to initialization and consumption of webhook jobs.
#[derive(Error, Debug)]
pub enum WorkerError {
    #[error("a database error occurred when executing a job")]
    DatabaseError(#[from] pgqueue::DatabaseError),
    #[error("a parsing error occurred in the underlying queue")]
    QueueParseError(#[from] pgqueue::ParseError),
    #[error("timed out while waiting for jobs to be available")]
    TimeoutError,
}
