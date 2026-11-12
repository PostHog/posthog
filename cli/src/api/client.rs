use std::{
    fmt::{Debug, Display},
    sync::{Arc, Mutex},
    time::Duration,
};

use anyhow::Result;
use reqwest::{
    blocking::{Client, RequestBuilder, Response},
    header::{HeaderMap, HeaderValue},
    Method, Url,
};
use serde::Deserialize;
use thiserror::Error;
use tracing::debug;

use crate::{
    invocation_context::InvocationConfig,
    utils::{ci::detailed_diagnostics, redact_request_error, redact_url, throttler::Throttler},
};
const ONE_MINUTE_IN_MS: u64 = 60 * 1000;

#[derive(Clone)]
pub struct PHClient {
    config: InvocationConfig,
    client: Client,
    throttler: Arc<Mutex<Throttler>>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn api_error(body: &str) -> ClientError {
        ClientError::ApiError(
            400,
            Box::new(Url::parse("https://example.com/api/test").unwrap()),
            body.to_string(),
        )
    }

    #[test]
    fn matches_structured_api_error_code() {
        let error = api_error(
            r#"{"type":"validation_error","code":"content_hash_mismatch","detail":"Different content","attr":null}"#,
        );

        assert!(error.has_api_error_code("content_hash_mismatch"));
        assert!(!error.has_api_error_code("release_id_mismatch"));
    }

    #[test]
    fn error_diagnostics_exclude_response_data_and_url_credentials() {
        for body in [
            r#"{"type":"validation_error","code":"invalid","detail":"BODY_SECRET","attr":"FIELD_SECRET","extra":{"key":"EXTRA_SECRET"}}"#,
            r#"{"type":"TYPE_SECRET","code":"CODE_SECRET"}"#,
            "BODY_SECRET FIELD_SECRET EXTRA_SECRET",
        ] {
            let error = ClientError::ApiError(
                400,
                Box::new(Url::parse("https://user:HOST_SECRET@example.com/api/test?token=QUERY_SECRET#FRAGMENT_SECRET").unwrap()),
                body.to_string(),
            );
            for output in [error.to_string(), format!("{error:?}")] {
                assert!(output.contains("400"), "{output}");
                assert!(output.contains("/api/test"), "{output}");
                for secret in [
                    "HOST_SECRET",
                    "QUERY_SECRET",
                    "FRAGMENT_SECRET",
                    "BODY_SECRET",
                    "FIELD_SECRET",
                    "EXTRA_SECRET",
                    "TYPE_SECRET",
                    "CODE_SECRET",
                ] {
                    assert!(!output.contains(secret), "{output}");
                }
            }
        }
    }

    #[test]
    fn api_error_message_shows_posthog_details_only_outside_ci() {
        let url =
            Url::parse("https://user:HOST_SECRET@example.com/api/test?token=QUERY_SECRET").unwrap();
        let drf = r#"{"type":"validation_error","code":"invalid","detail":"Release is locked.","attr":"release"}"#;
        let base = "API error: status='400' url='https://example.com/api/test'";

        for (body, show_detail, expected) in [
            (
                drf,
                true,
                format!("{base} error='validation_error' code='invalid' details='Release is locked.', attributes='release'"),
            ),
            (
                drf,
                false,
                format!("{base}. PostHog's error details are hidden in CI. Run the command outside CI to see them."),
            ),
            (
                r#"{"type":"validation_error\u001b","code":"invalid\u009d","detail":"café\n\tvalue\u0007","attr":"field\u009c"}"#,
                true,
                format!("{base} error='validation_error\\u001b' code='invalid\\u009d' details='café\n\tvalue\\u0007', attributes='field\\u009c'"),
            ),
            ("<html>BODY_SECRET</html>", true, base.to_string()),
            ("<html>BODY_SECRET</html>", false, base.to_string()),
        ] {
            assert_eq!(api_error_message(400, &url, body, show_detail), expected);
        }
    }

    #[test]
    fn falls_back_to_body_match_for_legacy_errors() {
        let error = api_error("legacy release_id_mismatch response");

        assert!(error.has_api_error_code("release_id_mismatch"));
    }
}

#[derive(Error)]
pub enum ClientError {
    RequestError(reqwest::Error),
    // All invalid status codes
    ApiError(u16, Box<Url>, String),
    InvalidUrl(String),
}

impl Display for ClientError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ClientError::RequestError(err) => {
                write!(f, "Request failed")?;
                if let Some(url) = err.url() {
                    write!(f, " for {}", redact_url(url))?;
                }
                if err.is_timeout() {
                    write!(f, " (timeout)")?;
                } else if err.is_connect() {
                    write!(f, " (connection error)")?;
                }
                Ok(())
            }
            ClientError::InvalidUrl(msg) => {
                write!(f, "Failed to build URL: {msg}")
            }
            ClientError::ApiError(status, url, body) => {
                write!(f, "{}", describe_api_failure(*status, url, body))
            }
        }
    }
}

#[derive(Deserialize)]
struct ApiErrorResponse {
    r#type: String,
    code: String,
    detail: String,
    attr: Option<String>,
}

pub fn describe_api_failure(status: u16, url: &Url, body: &str) -> String {
    api_error_message(status, url, body, detailed_diagnostics())
}

// Only a body in PostHog's error shape is ever shown. Any other body can be a proxy page or text
// that repeats the request, so it never appears, in CI or outside it.
fn api_error_message(status: u16, url: &Url, body: &str, show_detail: bool) -> String {
    let mut message = format!("API error: status='{status}' url='{}'", redact_url(url));

    let Ok(api_error) = serde_json::from_str::<ApiErrorResponse>(body) else {
        return message;
    };

    if !show_detail {
        message.push_str(
            ". PostHog's error details are hidden in CI. Run the command outside CI to see them.",
        );
        return message;
    }

    message.push_str(&format!(
        " error='{}' code='{}' details='{}'",
        api_error.r#type, api_error.code, api_error.detail
    ));
    if let Some(attr) = &api_error.attr {
        message.push_str(&format!(", attributes='{attr}'"));
    }
    let mut escaped = String::with_capacity(message.len());
    for character in message.chars() {
        if character.is_control() && !matches!(character, '\n' | '\t') {
            escaped.push_str(&format!("\\u{:04x}", character as u32));
        } else {
            escaped.push(character);
        }
    }
    escaped
}

impl Debug for ClientError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        Display::fmt(self, f)
    }
}

impl From<reqwest::Error> for ClientError {
    fn from(error: reqwest::Error) -> Self {
        ClientError::RequestError(redact_request_error(error))
    }
}

impl ClientError {
    pub fn has_structured_api_error_code(&self, expected_code: &str) -> bool {
        let ClientError::ApiError(_, _, body) = self else {
            return false;
        };

        api_error_code(body).is_some_and(|code| code == expected_code)
    }

    pub fn has_api_error_code(&self, expected_code: &str) -> bool {
        let ClientError::ApiError(_, _, body) = self else {
            return false;
        };

        self.has_structured_api_error_code(expected_code) || body.contains(expected_code)
    }
}

#[derive(Deserialize)]
struct ApiErrorCodeResponse {
    code: Option<String>,
}

fn api_error_code(body: &str) -> Option<String> {
    serde_json::from_str::<ApiErrorCodeResponse>(body)
        .ok()
        .and_then(|api_error| api_error.code)
}

pub trait SendRequestFn: FnOnce(RequestBuilder) -> RequestBuilder {}

impl PHClient {
    pub fn from_config(config: InvocationConfig) -> anyhow::Result<Self> {
        let client = Self::build_client(config.skip_ssl)?;
        let throttler = Arc::new(Mutex::new(Throttler::new(
            config.rate_limit,
            Duration::from_millis(ONE_MINUTE_IN_MS),
        )));
        Ok(Self {
            config,
            client,
            throttler,
        })
    }

    pub fn get(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::GET, url)
    }

    pub fn post(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::POST, url)
    }

    pub fn put(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::PUT, url)
    }

    pub fn delete(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::DELETE, url)
    }

    pub fn patch(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::PATCH, url)
    }

    pub fn send_get<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::GET, url, builder)
    }

    pub fn send_post<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::POST, url, builder)
    }

    pub fn send_delete<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::DELETE, url, builder)
    }

    pub fn send_put<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::PUT, url, builder)
    }

    pub fn send_request<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        method: Method,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.throttler.lock().unwrap().throttle();
        let request = builder(self.create_request(method, url));
        match request.send() {
            Ok(response) => {
                if response.status().is_success() {
                    Ok(response)
                } else {
                    let status = response.status().as_u16();
                    let box_url = Box::new(response.url().clone());
                    let body = response.text()?;
                    Err(ClientError::ApiError(status, box_url, body))
                }
            }
            Err(err) => Err(ClientError::from(err)),
        }
    }

    pub fn get_env_id(&self) -> &String {
        &self.config.env_id
    }

    fn create_request(&self, method: Method, url: Url) -> RequestBuilder {
        let headers = self.build_headers();
        debug!("building request for {method} {}", redact_url(&url));
        self.client
            .request(method, url)
            .bearer_auth(&self.config.api_key)
            .headers(headers)
    }

    fn build_client(skip_ssl: bool) -> anyhow::Result<Client> {
        let client = Client::builder()
            .danger_accept_invalid_certs(skip_ssl)
            .build()?;
        Ok(client)
    }

    fn build_headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert("Content-Type", HeaderValue::from_static("application/json"));
        headers.insert("User-Agent", HeaderValue::from_static("posthog-cli"));
        headers
    }

    pub fn env_url(&self, path: &str) -> Result<Url, ClientError> {
        self.build_url("environments", path)
    }

    pub fn project_url(&self, path: &str) -> Result<Url, ClientError> {
        self.build_url("projects", path)
    }

    fn build_url(&self, base: &str, path: &str) -> Result<Url, ClientError> {
        let host = self.config.host.clone();
        let env_id = self.config.env_id.clone();

        let base_url = Url::parse(&host)
            .map_err(|e| ClientError::InvalidUrl(e.to_string()))?
            .join(&format!("api/{base}/{env_id}/"))
            .map_err(|e| ClientError::InvalidUrl(e.to_string()))?
            .join(path)
            .map_err(|e| ClientError::InvalidUrl(e.to_string()))?;
        Ok(base_url)
    }
}
