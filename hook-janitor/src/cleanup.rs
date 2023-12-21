use async_trait::async_trait;
use std::result::Result;
use std::str::FromStr;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum CleanerError {
    #[error("invalid cleaner mode")]
    InvalidCleanerMode,
}

// Mode names, used by config/environment parsing to verify the mode is supported.
#[derive(Debug)]
pub enum CleanerModeName {
    Webhooks,
}

impl FromStr for CleanerModeName {
    type Err = CleanerError;

    fn from_str(s: &str) -> Result<Self, CleanerError> {
        match s {
            "webhooks" => Ok(CleanerModeName::Webhooks),
            _ => Err(CleanerError::InvalidCleanerMode),
        }
    }
}

// Right now, all this trait does is allow us to call `cleanup` in a loop in `main.rs`. There may
// be other benefits as we build this out, or we could remove it if it doesn't end up being useful.
#[async_trait]
pub trait Cleaner {
    async fn cleanup(&self);
}
