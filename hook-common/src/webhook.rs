use std::collections;
use std::convert::From;
use std::fmt;
use std::str::FromStr;

use serde::{de::Visitor, Deserialize, Serialize};

use crate::kafka_messages::{app_metrics, serialize_uuid};
use crate::pgqueue::PgQueueError;

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
    type Err = PgQueueError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_ascii_uppercase().as_ref() {
            "DELETE" => Ok(HttpMethod::DELETE),
            "GET" => Ok(HttpMethod::GET),
            "PATCH" => Ok(HttpMethod::PATCH),
            "POST" => Ok(HttpMethod::POST),
            "PUT" => Ok(HttpMethod::PUT),
            invalid => Err(PgQueueError::ParseHttpMethodError(invalid.to_owned())),
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

/// Convenience to cast `HttpMethod` to `http::Method`.
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
    pub body: String,
    pub headers: collections::HashMap<String, String>,
    pub method: HttpMethod,
    pub url: String,
}

/// `JobMetadata` required for the `WebhookConsumer` to execute a webhook.
/// These should be set if the Webhook is associated with a plugin `composeWebhook` invocation.
#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub struct WebhookJobMetadata {
    pub team_id: Option<i32>,
    pub plugin_id: Option<i32>,
    pub plugin_config_id: Option<i32>,
}

/// An error originating during a Webhook Job invocation.
#[derive(Serialize, Debug)]
pub struct WebhookJobError {
    pub r#type: app_metrics::ErrorType,
    pub details: app_metrics::ErrorDetails,
    #[serde(serialize_with = "serialize_uuid")]
    pub uuid: uuid::Uuid,
}

impl From<reqwest::Error> for WebhookJobError {
    fn from(error: reqwest::Error) -> Self {
        if error.is_body() || error.is_decode() {
            WebhookJobError::new_parse(&error.to_string())
        } else if error.is_timeout() {
            WebhookJobError::new_timeout(&error.to_string())
        } else if error.is_status() {
            WebhookJobError::new_http_status(
                error.status().expect("status code is defined").into(),
                &error.to_string(),
            )
        } else if error.is_connect()
            || error.is_builder()
            || error.is_request()
            || error.is_redirect()
        {
            // Builder errors seem to be related to unable to setup TLS, so I'm bundling them in connection.
            WebhookJobError::new_connection(&error.to_string())
        } else {
            // We can't match on Kind as some types do not have an associated variant in Kind (e.g. Timeout).
            unreachable!("We have covered all reqwest::Error types.")
        }
    }
}

impl WebhookJobError {
    pub fn new_timeout(message: &str) -> Self {
        let error_details = app_metrics::Error {
            name: "timeout".to_owned(),
            message: Some(message.to_owned()),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::Timeout,
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
            uuid: uuid::Uuid::now_v7(),
        }
    }

    pub fn new_connection(message: &str) -> Self {
        let error_details = app_metrics::Error {
            name: "connection error".to_owned(),
            message: Some(message.to_owned()),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::Connection,
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
            uuid: uuid::Uuid::now_v7(),
        }
    }

    pub fn new_http_status(status_code: u16, message: &str) -> Self {
        let error_details = app_metrics::Error {
            name: "http status".to_owned(),
            message: Some(message.to_owned()),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::HttpStatus(status_code),
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
            uuid: uuid::Uuid::now_v7(),
        }
    }

    pub fn new_parse(message: &str) -> Self {
        let error_details = app_metrics::Error {
            name: "parse error".to_owned(),
            message: Some(message.to_owned()),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::Parse,
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
            uuid: uuid::Uuid::now_v7(),
        }
    }

    pub fn new_max_attempts(max_attempts: i32) -> Self {
        let error_details = app_metrics::Error {
            name: "maximum attempts exceeded".to_owned(),
            message: Some(format!(
                "Exceeded maximum number of attempts ({}) for webhook",
                max_attempts
            )),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::MaxAttempts,
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
            uuid: uuid::Uuid::now_v7(),
        }
    }
}
