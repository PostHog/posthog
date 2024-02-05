use std::collections;
use std::convert::From;
use std::fmt;
use std::str::FromStr;

use chrono::{DateTime, Utc};
use serde::{de::Visitor, Deserialize, Serialize};

use crate::kafka_messages::app_metrics;
use crate::kafka_messages::{deserialize_datetime, serialize_datetime};
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

/// `JobParameters` required for the `WebhookWorker` to execute a webhook.
/// These parameters should match the exported Webhook interface that PostHog plugins.
/// implement. See: https://github.com/PostHog/plugin-scaffold/blob/main/src/types.ts#L15.
#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub struct WebhookJobParameters {
    pub body: String,
    pub headers: collections::HashMap<String, String>,
    pub method: HttpMethod,
    pub url: String,
}

/// `JobMetadata` required for the `WebhookWorker` to execute a webhook.
/// These should be set if the Webhook is associated with a plugin `composeWebhook` invocation.
#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub struct WebhookJobMetadata {
    pub team_id: u32,
    pub plugin_id: i32,
    pub plugin_config_id: i32,
    #[serde(
        serialize_with = "serialize_datetime",
        deserialize_with = "deserialize_datetime"
    )]
    pub created_at: DateTime<Utc>,
}

/// An error originating during a Webhook Job invocation.
/// This is to be serialized to be stored as an error whenever retrying or failing a webhook job.
#[derive(Deserialize, Serialize, Debug)]
pub struct WebhookJobError {
    pub r#type: app_metrics::ErrorType,
    pub details: app_metrics::ErrorDetails,
}

/// Webhook jobs boil down to an HTTP request, so it's useful to have a way to convert from &reqwest::Error.
/// For the convertion we check all possible error types with the associated is_* methods provided by reqwest.
/// Some precision may be lost as our app_metrics::ErrorType does not support the same number of variants.
impl From<&reqwest::Error> for WebhookJobError {
    fn from(error: &reqwest::Error) -> Self {
        if error.is_timeout() {
            WebhookJobError::new_timeout(&error.to_string())
        } else if error.is_status() {
            WebhookJobError::new_http_status(
                error.status().expect("status code is defined").into(),
                &error.to_string(),
            )
        } else {
            // Catch all other errors as `app_metrics::ErrorType::Connection` errors.
            // Not all of `reqwest::Error` may strictly be connection errors, so our supported error types may need an extension
            // depending on how strict error reporting has to be.
            WebhookJobError::new_connection(&error.to_string())
        }
    }
}

impl WebhookJobError {
    pub fn new_timeout(message: &str) -> Self {
        let error_details = app_metrics::Error {
            name: "Timeout Error".to_owned(),
            message: Some(message.to_owned()),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::TimeoutError,
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
        }
    }

    pub fn new_connection(message: &str) -> Self {
        let error_details = app_metrics::Error {
            name: "Connection Error".to_owned(),
            message: Some(message.to_owned()),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::ConnectionError,
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
        }
    }

    pub fn new_http_status(status_code: u16, message: &str) -> Self {
        let error_details = app_metrics::Error {
            name: "Bad Http Status".to_owned(),
            message: Some(message.to_owned()),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::BadHttpStatus(status_code),
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
        }
    }

    pub fn new_parse(message: &str) -> Self {
        let error_details = app_metrics::Error {
            name: "Parse Error".to_owned(),
            message: Some(message.to_owned()),
            stack: None,
        };
        Self {
            r#type: app_metrics::ErrorType::ParseError,
            details: app_metrics::ErrorDetails {
                error: error_details,
            },
        }
    }
}
