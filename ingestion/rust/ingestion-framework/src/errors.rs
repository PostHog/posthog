//! `is_retriable` reads only the top-level error, as Node reads `isRetriable` on the thrown object and not on its `cause`.

use std::fmt;
use std::sync::Arc;

#[derive(Debug, thiserror::Error)]
#[error("{message}")]
pub struct PipelineError {
    pub message: String,
    /// `Some(true)` retries, `Some(false)` goes to the DLQ, `None` retries and then crashes.
    pub retriable: Option<bool>,
}

impl PipelineError {
    pub fn retriable(message: impl Into<String>) -> anyhow::Error {
        anyhow::Error::new(Self {
            message: message.into(),
            retriable: Some(true),
        })
    }

    pub fn non_retriable(message: impl Into<String>) -> anyhow::Error {
        anyhow::Error::new(Self {
            message: message.into(),
            retriable: Some(false),
        })
    }
}

/// A `context()` wrapper reads as `None`, as in Node. A `SharedError` is one error object that several callers share, so it reads through.
pub fn is_retriable(error: &anyhow::Error) -> Option<bool> {
    // `anyhow`'s `downcast_ref` also finds a context wrapper's inner error, so check the outermost.
    let outermost: &(dyn std::error::Error + 'static) = error.chain().next()?;
    if let Some(pipeline_error) = outermost.downcast_ref::<PipelineError>() {
        return pipeline_error.retriable;
    }
    if let Some(shared) = outermost.downcast_ref::<SharedError>() {
        return is_retriable(&shared.0);
    }
    None
}

/// A poisoned pipeline rejects every later `next()` with the same error, and `anyhow::Error` is not `Clone`.
#[derive(Clone)]
pub struct SharedError(pub Arc<anyhow::Error>);

impl fmt::Debug for SharedError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Debug::fmt(&*self.0, f)
    }
}

impl fmt::Display for SharedError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(&*self.0, f)
    }
}

impl std::error::Error for SharedError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        self.0.source()
    }
}

pub fn shared_error(error: Arc<anyhow::Error>) -> anyhow::Error {
    anyhow::Error::new(SharedError(error))
}

pub fn join_error(error: tokio::task::JoinError) -> anyhow::Error {
    anyhow::anyhow!("pipeline task failed: {error}")
}

/// As in JavaScript's `AggregateError`, the message is `message` only, and a `None` sub error is Node's `undefined`.
pub struct AggregateError {
    pub message: String,
    pub errors: Vec<Option<Arc<anyhow::Error>>>,
}

impl fmt::Display for AggregateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl fmt::Debug for AggregateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("AggregateError")
            .field("message", &self.message)
            .field("errors", &self.errors)
            .finish()
    }
}

impl std::error::Error for AggregateError {}

pub fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(message) = payload.downcast_ref::<&str>() {
        (*message).to_string()
    } else if let Some(message) = payload.downcast_ref::<String>() {
        message.clone()
    } else {
        "unknown panic".to_string()
    }
}

/// A panic becomes an error logged with the element's origin, as a Node callback throw rejects `next()`.
pub fn call_user_fn<R>(
    kind: &str,
    name: &str,
    debug_context: Option<&serde_json::Value>,
    f: impl FnOnce() -> R,
) -> anyhow::Result<R> {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(f)) {
        Ok(value) => Ok(value),
        Err(payload) => {
            let message = panic_message(payload.as_ref());
            tracing::error!(error = %message, debug_context = ?debug_context, "{kind} {name} threw");
            Err(anyhow::anyhow!("{kind} {name} threw: {message}"))
        }
    }
}
