use std::time::Duration;
use thiserror::Error;

#[derive(Error, Debug, Clone)]
#[error("User Error: {msg}")]
pub struct UserError {
    pub msg: String,
}

impl UserError {
    pub fn new(msg: impl Into<String>) -> Self {
        Self { msg: msg.into() }
    }
}

pub trait ToUserError<T> {
    fn user_error(self, msg: impl Into<String>) -> anyhow::Result<T>;
}

// Use this to inject a user facing error message into the error chain
// Our main thread can extract this from an error chain and display it to the user
impl<T, E: std::error::Error + Send + Sync + 'static> ToUserError<T> for Result<T, E> {
    fn user_error(self, msg: impl Into<String>) -> anyhow::Result<T> {
        self.map_err(|e| anyhow::Error::from(e).context(UserError::new(msg)))
    }
}

const DEFAULT_USER_ERROR_MESSAGE: &str = "An unknown error occurred";

pub fn get_user_message(error: &anyhow::Error) -> &str {
    if let Some(user_error) = error.downcast_ref::<UserError>() {
        return &user_error.msg;
    }

    let mut source = error.source();
    while let Some(err) = source {
        if let Some(user_error) = err.downcast_ref::<UserError>() {
            return &user_error.msg;
        }
        source = err.source();
    }

    DEFAULT_USER_ERROR_MESSAGE
}

#[derive(Error, Debug)]
#[error("Rate limited")]
pub struct RateLimitedError {
    pub retry_after: Option<Duration>,
    #[source]
    pub source: reqwest::Error,
}

/// Extracts a Retry-After duration if a RateLimitedError is present in the error chain
pub fn extract_retry_after_from_error(error: &anyhow::Error) -> Option<Duration> {
    if let Some(rl) = error.downcast_ref::<RateLimitedError>() {
        return rl.retry_after;
    }

    let mut source = error.source();
    while let Some(err) = source {
        if let Some(rl) = err.downcast_ref::<RateLimitedError>() {
            return rl.retry_after;
        }
        source = err.source();
    }
    None
}

/// Returns true if the error chain contains a reqwest::Error with HTTP 429.
pub fn is_rate_limited_error(error: &anyhow::Error) -> bool {
    // Our custom rate limit error also counts
    if error.downcast_ref::<RateLimitedError>().is_some() {
        return true;
    }

    if let Some(reqwest_err) = error.downcast_ref::<reqwest::Error>() {
        if reqwest_err.status().is_some_and(|s| s.as_u16() == 429) {
            return true;
        }
    }

    let mut source = error.source();
    while let Some(err) = source {
        if let Some(reqwest_err) = err.downcast_ref::<reqwest::Error>() {
            if reqwest_err.status().is_some_and(|s| s.as_u16() == 429) {
                return true;
            }
        }
        source = err.source();
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::anyhow;
    use httpmock::MockServer;
    use reqwest::Client;

    #[test]
    fn test_user_error_as_root() {
        let user_error = UserError::new("Root user error message");
        let error = anyhow::Error::from(user_error);

        let result = get_user_message(&error);
        assert_eq!(result, "Root user error message");
    }

    #[test]
    fn test_user_error_in_middle_of_chain() {
        let io_error = std::io::Error::new(std::io::ErrorKind::NotFound, "File not found");
        let user_error = UserError::new("User-friendly file error");

        let error = anyhow::Error::from(io_error)
            .context(user_error)
            .context("High level operation failed");

        let result = get_user_message(&error);
        assert_eq!(result, "User-friendly file error");
    }

    #[test]
    fn test_user_error_at_end_of_chain() {
        let user_error = UserError::new("Deep user error");
        let error = anyhow::Error::from(user_error)
            .context("Middle layer error")
            .context("Top level error");

        let result = get_user_message(&error);
        assert_eq!(result, "Deep user error");
    }

    #[test]
    fn test_multiple_user_errors_in_chain() {
        let deep_user_error = UserError::new("Deep user error");
        let middle_user_error = UserError::new("Middle user error");

        let error = anyhow::Error::from(deep_user_error)
            .context("Some system error")
            .context(middle_user_error)
            .context("Top level error");

        let result = get_user_message(&error);
        assert_eq!(result, "Middle user error");
    }

    #[test]
    fn test_multiple_user_errors_with_root_user_error() {
        let deep_user_error = UserError::new("Deep user error");
        let root_user_error = UserError::new("Root user error");

        let error = anyhow::Error::from(deep_user_error)
            .context("Some system error")
            .context(root_user_error);

        let result = get_user_message(&error);
        assert_eq!(result, "Root user error");
    }

    #[test]
    fn test_no_user_error_in_chain() {
        let io_error = std::io::Error::new(std::io::ErrorKind::PermissionDenied, "Access denied");
        let error = anyhow::Error::from(io_error)
            .context("Failed to read config")
            .context("Application startup failed");

        let result = get_user_message(&error);
        assert_eq!(result, DEFAULT_USER_ERROR_MESSAGE);
    }

    #[test]
    fn test_single_non_user_error() {
        let simple_error = anyhow!("Simple error message");

        let result = get_user_message(&simple_error);
        assert_eq!(result, DEFAULT_USER_ERROR_MESSAGE);
    }

    #[test]
    fn test_user_error_trait_integration() {
        let io_error = std::io::Error::new(std::io::ErrorKind::NotFound, "File not found");
        let result: anyhow::Result<()> =
            Err(io_error).user_error("Could not find configuration file");

        let error = result.unwrap_err();
        let user_message = get_user_message(&error);
        assert_eq!(user_message, "Could not find configuration file");
    }

    #[tokio::test]
    async fn test_is_rate_limited_error_true_for_429() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/rl");
            then.status(429);
        });

        let client = Client::new();
        let resp = client.get(server.url("/rl")).send().await.unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);
        assert!(is_rate_limited_error(&err));
    }

    #[tokio::test]
    async fn test_is_rate_limited_error_false_for_non_429() {
        let server = MockServer::start();
        let _mock = server.mock(|when, then| {
            when.method(httpmock::Method::GET).path("/err");
            then.status(500);
        });

        let client = Client::new();
        let resp = client.get(server.url("/err")).send().await.unwrap();
        let http_err = resp.error_for_status().unwrap_err();
        let err = anyhow::Error::from(http_err);
        assert!(!is_rate_limited_error(&err));
    }
}
