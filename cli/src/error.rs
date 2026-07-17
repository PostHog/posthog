use std::{
    error::Error as StdError,
    fmt::{self, Display},
};

use anyhow::Error;
use posthog_rs::CaptureExceptionOptions;
use serde::Deserialize;
use tracing::debug;

use crate::{api::client::ClientError, invocation_context::current_telemetry_command_name};

pub struct CapturedError {
    pub inner: Error,
    pub exception_id: Option<String>,
}

impl CapturedError {
    pub fn capture(self) -> Self {
        capture_exception(ErrorTelemetryMetadata::from_error(&self.inner));
        self
    }
}

impl From<Error> for CapturedError {
    fn from(inner: Error) -> Self {
        Self {
            inner,
            exception_id: None,
        }
    }
}

#[derive(Debug)]
struct SanitizedCliError;

impl Display for SanitizedCliError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "CLI command failed")
    }
}

impl StdError for SanitizedCliError {}

struct ErrorTelemetryMetadata {
    error_kind: &'static str,
    command_name: String,
    chain_depth: usize,
    http_status: Option<u16>,
    api_error_code: Option<String>,
    is_timeout: Option<bool>,
    is_connect: Option<bool>,
}

impl ErrorTelemetryMetadata {
    fn from_error(error: &Error) -> Self {
        let command_name =
            current_telemetry_command_name().unwrap_or_else(|| "unknown".to_string());
        let chain_depth = error.chain().count();

        let Some(client_error) = error
            .chain()
            .find_map(|source| source.downcast_ref::<ClientError>())
        else {
            return Self {
                error_kind: "other",
                command_name,
                chain_depth,
                http_status: None,
                api_error_code: None,
                is_timeout: None,
                is_connect: None,
            };
        };

        match client_error {
            ClientError::ApiError(status, _, body) => Self {
                error_kind: "api_error",
                command_name,
                chain_depth,
                http_status: Some(*status),
                api_error_code: safe_api_error_code(body),
                is_timeout: None,
                is_connect: None,
            },
            ClientError::RequestError(err) => Self {
                error_kind: "request_error",
                command_name,
                chain_depth,
                http_status: None,
                api_error_code: None,
                is_timeout: Some(err.is_timeout()),
                is_connect: Some(err.is_connect()),
            },
            ClientError::InvalidUrl(_) => Self {
                error_kind: "invalid_url",
                command_name,
                chain_depth,
                http_status: None,
                api_error_code: None,
                is_timeout: None,
                is_connect: None,
            },
        }
    }

    fn fingerprint(&self) -> String {
        let mut parts = vec![
            "posthog-cli".to_string(),
            self.command_name.clone(),
            self.error_kind.to_string(),
        ];

        if let Some(status) = self.http_status {
            parts.push(status.to_string());
        }

        if let Some(api_error_code) = &self.api_error_code {
            parts.push(api_error_code.clone());
        }

        parts.join(":")
    }
}

#[derive(Deserialize)]
struct ApiErrorCodeResponse {
    code: Option<String>,
}

fn safe_api_error_code(body: &str) -> Option<String> {
    let code = serde_json::from_str::<ApiErrorCodeResponse>(body)
        .ok()?
        .code?;
    if code.len() > 64
        || !code
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        return None;
    }
    Some(code)
}

fn capture_exception(metadata: ErrorTelemetryMetadata) {
    let mut options = match CaptureExceptionOptions::new()
        .fingerprint(metadata.fingerprint())
        .property("error_kind", metadata.error_kind)
        .and_then(|options| options.property("error_chain_depth", metadata.chain_depth))
        .and_then(|options| options.property("command_name", metadata.command_name.as_str()))
    {
        Ok(options) => options,
        Err(err) => {
            debug!("Failed to build exception capture options: {err:?}");
            return;
        }
    };

    if let Some(http_status) = metadata.http_status {
        options = match options.property("http_status", http_status) {
            Ok(options) => options,
            Err(err) => {
                debug!("Failed to attach exception status: {err:?}");
                return;
            }
        };
    }

    if let Some(api_error_code) = metadata.api_error_code {
        options = match options.property("api_error_code", api_error_code) {
            Ok(options) => options,
            Err(err) => {
                debug!("Failed to attach exception API error code: {err:?}");
                return;
            }
        };
    }

    if let Some(is_timeout) = metadata.is_timeout {
        options = match options.property("is_timeout", is_timeout) {
            Ok(options) => options,
            Err(err) => {
                debug!("Failed to attach exception timeout flag: {err:?}");
                return;
            }
        };
    }

    if let Some(is_connect) = metadata.is_connect {
        options = match options.property("is_connect", is_connect) {
            Ok(options) => options,
            Err(err) => {
                debug!("Failed to attach exception connection flag: {err:?}");
                return;
            }
        };
    }

    if let Err(err) = posthog_rs::capture_exception_with(&SanitizedCliError, options) {
        debug!("Failed to capture exception: {err:?}");
    }
}
