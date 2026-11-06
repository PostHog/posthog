use anyhow::Result;

/// Unwrap a spawn_blocking JoinHandle<Result<T>> into Result<T>.
///
/// This helper handles the two-level Result structure returned by spawn_blocking
/// when the inner function returns an anyhow::Result:
/// - `Ok(Ok(value))` - Task completed successfully with a success result
/// - `Ok(Err(e))` - Task completed successfully but the operation inside failed
/// - `Err(join_err)` - Task panicked or was cancelled
///
/// The panic_context parameter provides additional context for task panic errors.
pub async fn unwrap_blocking_task<T>(
    handle: tokio::task::JoinHandle<Result<T>>,
    panic_context: &str,
) -> Result<T>
where
    T: Send + 'static,
{
    match handle.await {
        Ok(Ok(value)) => Ok(value),
        Ok(Err(e)) => Err(e),
        Err(join_err) => Err(anyhow::Error::from(join_err).context(panic_context.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_unwrap_blocking_task_success() {
        let handle = tokio::task::spawn_blocking(|| -> Result<i32> { Ok(42) });

        let result = unwrap_blocking_task(handle, "test operation panicked").await;

        assert!(result.is_ok());
        assert_eq!(result.unwrap(), 42);
    }

    #[tokio::test]
    async fn test_unwrap_blocking_task_error() {
        let handle = tokio::task::spawn_blocking(|| -> Result<i32> {
            Err(anyhow::Error::new(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                "file not found",
            )))
        });

        let result = unwrap_blocking_task(handle, "test operation panicked").await;

        assert!(result.is_err());
        let err_str = result.unwrap_err().to_string();
        assert!(err_str.contains("file not found"));
    }

    #[tokio::test]
    async fn test_unwrap_blocking_task_panic() {
        let handle = tokio::task::spawn_blocking(|| -> Result<i32> { panic!("oops") });

        let result = unwrap_blocking_task(handle, "test operation panicked").await;

        assert!(result.is_err());
        let err_str = result.unwrap_err().to_string();
        assert!(err_str.contains("test operation panicked"));
    }
}
