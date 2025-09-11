use anyhow::Error;

pub struct CapturedError {
    pub inner: Error,
    pub exception_id: Option<String>,
}

impl From<Error> for CapturedError {
    fn from(inner: Error) -> Self {
        Self {
            inner,
            exception_id: None,
        }
    }
}
