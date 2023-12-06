use std::collections;
use std::fmt;
use std::str::FromStr;
use std::time;

use async_std::task;
use hook_common::pgqueue::{PgJobError, PgQueue, PgQueueError, PgTransactionJob};
use http::StatusCode;
use serde::{de::Visitor, Deserialize, Serialize};
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
    QueueError(#[from] PgQueueError),
    #[error("an error occurred in the underlying job")]
    PgJobError(String),
    #[error("an error occurred when attempting to send a request")]
    RequestError(#[from] reqwest::Error),
    #[error("a webhook could not be delivered but it could be retried later: {reason}")]
    RetryableWebhookError {
        reason: String,
        retry_after: Option<time::Duration>,
    },
    #[error("a webhook could not be delivered and it cannot be retried further: {0}")]
    NonRetryableWebhookError(String),
}

/// Supported HTTP methods for webhooks.
#[derive(Debug, PartialEq, Clone, Copy)]
pub enum HttpMethod {
    DELETE,
    GET,
    PATCH,
    POST,
    PUT,
}

/// Allow casting `HttpMethod` from strings.
impl FromStr for HttpMethod {
    type Err = WebhookConsumerError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_ascii_uppercase().as_ref() {
            "DELETE" => Ok(HttpMethod::DELETE),
            "GET" => Ok(HttpMethod::GET),
            "PATCH" => Ok(HttpMethod::PATCH),
            "POST" => Ok(HttpMethod::POST),
            "PUT" => Ok(HttpMethod::PUT),
            invalid => Err(WebhookConsumerError::ParseHttpMethodError(
                invalid.to_owned(),
            )),
        }
    }
}

/// Implement `std::fmt::Display` to convert HttpMethod to string.
impl fmt::Display for HttpMethod {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            HttpMethod::DELETE => write!(f, "DELETE"),
            HttpMethod::GET => write!(f, "GET"),
            HttpMethod::PATCH => write!(f, "PATCH"),
            HttpMethod::POST => write!(f, "POST"),
            HttpMethod::PUT => write!(f, "PUT"),
        }
    }
}

struct HttpMethodVisitor;

impl<'de> Visitor<'de> for HttpMethodVisitor {
    type Value = HttpMethod;

    fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
        write!(formatter, "the string representation of HttpMethod")
    }

    fn visit_str<E>(self, s: &str) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        match HttpMethod::from_str(s) {
            Ok(method) => Ok(method),
            Err(_) => Err(serde::de::Error::invalid_value(
                serde::de::Unexpected::Str(s),
                &self,
            )),
        }
    }
}

/// Deserialize required to read `HttpMethod` from database.
impl<'de> Deserialize<'de> for HttpMethod {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_str(HttpMethodVisitor)
    }
}

/// Serialize required to write `HttpMethod` to database.
impl Serialize for HttpMethod {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.to_string())
    }
}

/// Convinience to cast `HttpMethod` to `http::Method`.
/// Not all `http::Method` variants are valid `HttpMethod` variants, hence why we
/// can't just use the former or implement `From<HttpMethod>`.
impl From<HttpMethod> for http::Method {
    fn from(val: HttpMethod) -> Self {
        match val {
            HttpMethod::DELETE => http::Method::DELETE,
            HttpMethod::GET => http::Method::GET,
            HttpMethod::PATCH => http::Method::PATCH,
            HttpMethod::POST => http::Method::POST,
            HttpMethod::PUT => http::Method::PUT,
        }
    }
}

impl From<&HttpMethod> for http::Method {
    fn from(val: &HttpMethod) -> Self {
        match val {
            HttpMethod::DELETE => http::Method::DELETE,
            HttpMethod::GET => http::Method::GET,
            HttpMethod::PATCH => http::Method::PATCH,
            HttpMethod::POST => http::Method::POST,
            HttpMethod::PUT => http::Method::PUT,
        }
    }
}

/// `JobParameters` required for the `WebhookConsumer` to execute a webhook.
/// These parameters should match the exported Webhook interface that PostHog plugins.
/// implement. See: https://github.com/PostHog/plugin-scaffold/blob/main/src/types.ts#L15.
#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub struct WebhookJobParameters {
    body: String,
    headers: collections::HashMap<String, String>,
    method: HttpMethod,
    url: String,
}

/// A consumer to poll `PgQueue` and spawn tasks to process webhooks when a job becomes available.
pub struct WebhookConsumer<'p> {
    /// An identifier for this consumer. Used to mark jobs we have consumed.
    name: String,
    /// The queue we will be dequeuing jobs from.
    queue: &'p PgQueue,
    /// The interval for polling the queue.
    poll_interval: time::Duration,
    /// A timeout for webhook requests.
    request_timeout: time::Duration,
}

impl<'p> WebhookConsumer<'p> {
    pub fn new(
        name: &str,
        queue: &'p PgQueue,
        poll_interval: time::Duration,
        request_timeout: time::Duration,
    ) -> Self {
        Self {
            name: name.to_owned(),
            queue,
            poll_interval,
            request_timeout,
        }
    }

    /// Wait until a job becomes available in our queue.
    async fn wait_for_job<'a>(
        &self,
    ) -> Result<PgTransactionJob<'a, WebhookJobParameters>, WebhookConsumerError> {
        loop {
            if let Some(job) = self.queue.dequeue_tx(&self.name).await? {
                return Ok(job);
            } else {
                task::sleep(self.poll_interval).await;
            }
        }
    }

    /// Run this consumer to continuously process any jobs that become available.
    pub async fn run(&self) -> Result<(), WebhookConsumerError> {
        loop {
            let webhook_job = self.wait_for_job().await?;

            let request_timeout = self.request_timeout; // Required to avoid capturing self in closure.
            tokio::spawn(async move { process_webhook_job(webhook_job, request_timeout).await });
        }
    }
}

/// Process a webhook job by transitioning it to its appropriate state after its request is sent.
/// After we finish, the webhook job will be set as completed (if the request was successful), retryable (if the request
/// was unsuccessful but we can still attempt a retry), or failed (if the request was unsuccessful and no more retries
/// may be attempted).
///
/// A webhook job is considered retryable after a failing request if:
/// 1. The job has attempts remaining (i.e. hasn't reached `max_attempts`), and...
/// 2. The status code indicates retrying at a later point could resolve the issue. This means: 429 and any 5XX.
///
/// # Arguments
///
/// * `webhook_job`: The webhook job to process as dequeued from `hook_common::pgqueue::PgQueue`.
/// * `request_timeout`: A timeout for the HTTP request.
async fn process_webhook_job(
    webhook_job: PgTransactionJob<'_, WebhookJobParameters>,
    request_timeout: std::time::Duration,
) -> Result<(), WebhookConsumerError> {
    match send_webhook(
        &webhook_job.job.parameters.method,
        &webhook_job.job.parameters.url,
        &webhook_job.job.parameters.headers,
        webhook_job.job.parameters.body.clone(),
        request_timeout,
    )
    .await
    {
        Ok(_) => {
            webhook_job
                .complete()
                .await
                .map_err(|error| WebhookConsumerError::PgJobError(error.to_string()))?;
            Ok(())
        }
        Err(WebhookConsumerError::RetryableWebhookError {
            reason,
            retry_after,
        }) => match webhook_job.retry(reason.to_string(), retry_after).await {
            Ok(_) => Ok(()),
            Err(PgJobError::RetryInvalidError {
                job: webhook_job,
                error: fail_error,
            }) => {
                webhook_job
                    .fail(fail_error.to_string())
                    .await
                    .map_err(|job_error| WebhookConsumerError::PgJobError(job_error.to_string()))?;
                Ok(())
            }
            Err(job_error) => Err(WebhookConsumerError::PgJobError(job_error.to_string())),
        },
        Err(error) => {
            webhook_job
                .fail(error.to_string())
                .await
                .map_err(|job_error| WebhookConsumerError::PgJobError(job_error.to_string()))?;
            Ok(())
        }
    }
}

/// Make an HTTP request to a webhook endpoint.
///
/// # Arguments
///
/// * `method`: The HTTP method to use in the HTTP request.
/// * `url`: The URL we are targetting with our request. Parsing this URL fail.
/// * `headers`: Key, value pairs of HTTP headers in a `std::collections::HashMap`. Can fail if headers are not valid.
/// * `body`: The body of the request. Ownership is required.
/// * `timeout`: A timeout for the HTTP request.
async fn send_webhook(
    method: &HttpMethod,
    url: &str,
    headers: &collections::HashMap<String, String>,
    body: String,
    timeout: std::time::Duration,
) -> Result<reqwest::Response, WebhookConsumerError> {
    let client = reqwest::Client::new();
    let method: http::Method = method.into();
    let url: reqwest::Url = (url).parse().map_err(WebhookConsumerError::ParseUrlError)?;
    let headers: reqwest::header::HeaderMap = (headers)
        .try_into()
        .map_err(WebhookConsumerError::ParseHeadersError)?;

    let body = reqwest::Body::from(body);
    let response = client
        .request(method, url)
        .headers(headers)
        .timeout(timeout)
        .body(body)
        .send()
        .await?;

    let status = response.status();

    if status.is_success() {
        Ok(response)
    } else if is_retryable_status(status) {
        let retry_after = parse_retry_after_header(response.headers());

        Err(WebhookConsumerError::RetryableWebhookError {
            reason: format!("retryable status code {}", status),
            retry_after,
        })
    } else {
        Err(WebhookConsumerError::NonRetryableWebhookError(format!(
            "non-retryable status code {}",
            status
        )))
    }
}

fn is_retryable_status(status: StatusCode) -> bool {
    status == StatusCode::TOO_MANY_REQUESTS || status.is_server_error()
}

/// Attempt to parse a chrono::Duration from a Retry-After header, returning None if not possible.
/// Retry-After header can specify a date in RFC2822 or a number of seconds; we try to parse both.
/// If a Retry-After header is not present in the provided `header_map`, `None` is returned.
///
/// # Arguments
///
/// * `header_map`: A `&reqwest::HeaderMap` of response headers that could contain Retry-After.
fn parse_retry_after_header(header_map: &reqwest::header::HeaderMap) -> Option<time::Duration> {
    let retry_after_header = header_map.get(reqwest::header::RETRY_AFTER);

    let retry_after = match retry_after_header {
        Some(header_value) => match header_value.to_str() {
            Ok(s) => s,
            Err(_) => {
                return None;
            }
        },
        None => {
            return None;
        }
    };

    if let Ok(u) = retry_after.parse::<u64>() {
        let duration = time::Duration::from_secs(u);
        return Some(duration);
    }

    if let Ok(dt) = chrono::DateTime::parse_from_rfc2822(retry_after) {
        let duration =
            chrono::DateTime::<chrono::offset::Utc>::from(dt) - chrono::offset::Utc::now();

        // This can only fail when negative, in which case we return None.
        return duration.to_std().ok();
    }

    None
}

mod tests {
    use super::*;
    // Note we are ignoring some warnings in this module.
    // This is due to a long-standing cargo bug that reports imports and helper functions as unused.
    // See: https://github.com/rust-lang/rust/issues/46379.
    #[allow(unused_imports)]
    use hook_common::pgqueue::{JobStatus, NewJob, RetryPolicy};

    /// Use process id as a worker id for tests.
    #[allow(dead_code)]
    fn worker_id() -> String {
        std::process::id().to_string()
    }

    #[allow(dead_code)]
    async fn enqueue_job(
        queue: &PgQueue,
        max_attempts: i32,
        job_parameters: WebhookJobParameters,
    ) -> Result<(), PgQueueError> {
        let job_target = job_parameters.url.to_owned();
        let new_job = NewJob::new(max_attempts, job_parameters, &job_target);
        queue.enqueue(new_job).await?;
        Ok(())
    }

    #[test]
    fn test_is_retryable_status() {
        assert!(!is_retryable_status(http::StatusCode::FORBIDDEN));
        assert!(!is_retryable_status(http::StatusCode::BAD_REQUEST));
        assert!(is_retryable_status(http::StatusCode::TOO_MANY_REQUESTS));
        assert!(is_retryable_status(http::StatusCode::INTERNAL_SERVER_ERROR));
    }

    #[test]
    fn test_parse_retry_after_header() {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(reqwest::header::RETRY_AFTER, "120".parse().unwrap());

        let duration = parse_retry_after_header(&headers).unwrap();
        assert_eq!(duration, time::Duration::from_secs(120));

        headers.remove(reqwest::header::RETRY_AFTER);

        let duration = parse_retry_after_header(&headers);
        assert_eq!(duration, None);

        headers.insert(
            reqwest::header::RETRY_AFTER,
            "Wed, 21 Oct 2015 07:28:00 GMT".parse().unwrap(),
        );

        let duration = parse_retry_after_header(&headers);
        assert_eq!(duration, None);
    }

    #[tokio::test]
    async fn test_wait_for_job() {
        let worker_id = worker_id();
        let queue_name = "test_wait_for_job".to_string();
        let table_name = "job_queue".to_string();
        let db_url = "postgres://posthog:posthog@localhost:15432/test_database".to_string();
        let queue = PgQueue::new(&queue_name, &table_name, &db_url, RetryPolicy::default())
            .await
            .expect("failed to connect to PG");

        let webhook_job = WebhookJobParameters {
            body: "a webhook job body. much wow.".to_owned(),
            headers: collections::HashMap::new(),
            method: HttpMethod::POST,
            url: "localhost".to_owned(),
        };
        // enqueue takes ownership of the job enqueued to avoid bugs that can cause duplicate jobs.
        // Normally, a separate application would be enqueueing jobs for us to consume, so no ownership
        // conflicts would arise. However, in this test we need to do the enqueueing ourselves.
        // So, we clone the job to keep it around and assert the values returned by wait_for_job.
        enqueue_job(&queue, 1, webhook_job.clone())
            .await
            .expect("failed to enqueue job");
        let consumer = WebhookConsumer::new(
            &worker_id,
            &queue,
            time::Duration::from_millis(100),
            time::Duration::from_millis(5000),
        );
        let consumed_job = consumer
            .wait_for_job()
            .await
            .expect("failed to wait and read job");

        assert_eq!(consumed_job.job.attempt, 1);
        assert!(consumed_job.job.attempted_by.contains(&worker_id));
        assert_eq!(consumed_job.job.attempted_by.len(), 1);
        assert_eq!(consumed_job.job.max_attempts, 1);
        assert_eq!(*consumed_job.job.parameters.as_ref(), webhook_job);
        assert_eq!(consumed_job.job.status, JobStatus::Running);
        assert_eq!(consumed_job.job.target, webhook_job.url);

        consumed_job
            .complete()
            .await
            .expect("job not successfully completed");
    }

    #[tokio::test]
    async fn test_send_webhook() {
        let method = HttpMethod::POST;
        let url = "http://localhost:18081/echo";
        let headers = collections::HashMap::new();
        let body = "a very relevant request body";
        let response = send_webhook(
            &method,
            url,
            &headers,
            body.to_owned(),
            time::Duration::from_millis(5000),
        )
        .await
        .expect("send_webhook failed");

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.text().await.expect("failed to read response body"),
            body.to_owned(),
        );
    }
}
