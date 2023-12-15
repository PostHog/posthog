use std::time;

use hook_common::pgqueue;
use thiserror::Error;

/// Enumeration of errors for operations with WebhookConsumer.
#[derive(Error, Debug)]
pub enum WebhookConsumerError {
    #[error("timed out while waiting for jobs to be available")]
    TimeoutError,
    #[error("{0} is not a valid HttpMethod")]
    ParseHttpMethodError(String),
    #[error("error parsing webhook headers")]
    ParseHeadersError(http::Error),
    #[error("error parsing webhook url")]
    ParseUrlError(url::ParseError),
    #[error("an error occurred in the underlying queue")]
    QueueError(#[from] pgqueue::PgQueueError),
    #[error("an error occurred in the underlying job")]
    PgJobError(String),
    #[error("a webhook could not be delivered but it could be retried later: {reason}")]
    RetryableWebhookError {
        reason: String,
        retry_after: Option<time::Duration>,
    },
    #[error("a webhook could not be delivered and it cannot be retried further: {0}")]
    NonRetryableWebhookError(String),
}
