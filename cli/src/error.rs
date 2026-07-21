use std::{
    error::Error as StdError,
    fmt::{self, Display},
};

use anyhow::Error;
use posthog_rs::CaptureExceptionOptions;
use serde::Deserialize;
use tracing::debug;

use crate::{
    api::client::ClientError, api_proxy::ApiProxyError,
    invocation_context::current_telemetry_command_name,
};

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
    proxy_error_kind: Option<&'static str>,
    proxy_step: Option<&'static str>,
    io_error_kind: Option<String>,
}

impl ErrorTelemetryMetadata {
    fn from_error(error: &Error) -> Self {
        let command_name =
            current_telemetry_command_name().unwrap_or_else(|| "unknown".to_string());
        let chain_depth = error.chain().count();

        let mut metadata = Self {
            error_kind: "other",
            command_name,
            chain_depth,
            http_status: None,
            api_error_code: None,
            is_timeout: None,
            is_connect: None,
            proxy_error_kind: None,
            proxy_step: None,
            io_error_kind: None,
        };

        if let Some(proxy_error) = error
            .chain()
            .find_map(|source| source.downcast_ref::<ApiProxyError>())
        {
            metadata.error_kind = "proxy_launch_error";
            metadata.proxy_error_kind = Some(proxy_error.telemetry_kind());
            metadata.proxy_step = proxy_error.telemetry_step();
            metadata.io_error_kind = proxy_error.telemetry_io_error_kind();
            return metadata;
        }

        let Some(client_error) = error
            .chain()
            .find_map(|source| source.downcast_ref::<ClientError>())
        else {
            return metadata;
        };

        match client_error {
            ClientError::ApiError(status, _, body) => {
                metadata.error_kind = "api_error";
                metadata.http_status = Some(*status);
                metadata.api_error_code = safe_api_error_code(body);
            }
            ClientError::RequestError(err) => {
                metadata.error_kind = "request_error";
                metadata.is_timeout = Some(err.is_timeout());
                metadata.is_connect = Some(err.is_connect());
            }
            ClientError::InvalidUrl(_) => {
                metadata.error_kind = "invalid_url";
            }
        }

        metadata
    }

    fn fingerprint(&self) -> String {
        let mut parts = vec![
            "posthog-cli".to_string(),
            self.command_name.clone(),
            self.error_kind.to_string(),
        ];

        if let Some(proxy_error_kind) = self.proxy_error_kind {
            parts.push(proxy_error_kind.to_string());
        }

        if let Some(proxy_step) = self.proxy_step {
            parts.push(proxy_step.to_string());
        }

        if let Some(io_error_kind) = &self.io_error_kind {
            parts.push(io_error_kind.clone());
        }

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

    if let Some(proxy_error_kind) = metadata.proxy_error_kind {
        options = match options.property("proxy_error_kind", proxy_error_kind) {
            Ok(options) => options,
            Err(err) => {
                debug!("Failed to attach exception proxy error kind: {err:?}");
                return;
            }
        };
    }

    if let Some(proxy_step) = metadata.proxy_step {
        options = match options.property("proxy_step", proxy_step) {
            Ok(options) => options,
            Err(err) => {
                debug!("Failed to attach exception proxy step: {err:?}");
                return;
            }
        };
    }

    if let Some(io_error_kind) = metadata.io_error_kind {
        options = match options.property("io_error_kind", io_error_kind) {
            Ok(options) => options,
            Err(err) => {
                debug!("Failed to attach exception io error kind: {err:?}");
                return;
            }
        };
    }

    if let Err(err) = posthog_rs::capture_exception_with(&SanitizedCliError, options) {
        debug!("Failed to capture exception: {err:?}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api_proxy::{ApiProxyError, MaterializeStep};

    #[test]
    fn proxy_launch_errors_produce_structured_telemetry() {
        let error = anyhow::Error::new(ApiProxyError::MaterializeFailed {
            step: MaterializeStep::Write,
            path: "/home/user/.posthog/api-cli".to_string(),
            source: std::io::Error::new(std::io::ErrorKind::PermissionDenied, "denied"),
        })
        .context("wrapped for good measure");

        let metadata = ErrorTelemetryMetadata::from_error(&error);

        assert_eq!(metadata.error_kind, "proxy_launch_error");
        assert_eq!(metadata.proxy_error_kind, Some("materialize_failed"));
        assert_eq!(metadata.proxy_step, Some("write"));
        assert_eq!(metadata.io_error_kind.as_deref(), Some("PermissionDenied"));
        // command_name comes from mutable global telemetry state, so only pin
        // the parts of the fingerprint this test controls.
        assert!(metadata.fingerprint().starts_with("posthog-cli:"));
        assert!(metadata
            .fingerprint()
            .ends_with(":proxy_launch_error:materialize_failed:write:PermissionDenied"));
    }

    #[test]
    fn bundle_not_embedded_has_no_io_details() {
        let error = anyhow::Error::new(ApiProxyError::BundleNotEmbedded);

        let metadata = ErrorTelemetryMetadata::from_error(&error);

        assert_eq!(metadata.error_kind, "proxy_launch_error");
        assert_eq!(metadata.proxy_error_kind, Some("bundle_not_embedded"));
        assert_eq!(metadata.proxy_step, None);
        assert_eq!(metadata.io_error_kind, None);
        assert!(metadata
            .fingerprint()
            .ends_with(":proxy_launch_error:bundle_not_embedded"));
    }

    #[test]
    fn unclassified_errors_stay_other() {
        let error = anyhow::anyhow!("something else entirely");

        let metadata = ErrorTelemetryMetadata::from_error(&error);

        assert_eq!(metadata.error_kind, "other");
        assert_eq!(metadata.proxy_error_kind, None);
        assert!(metadata.fingerprint().ends_with(":other"));
    }
}
