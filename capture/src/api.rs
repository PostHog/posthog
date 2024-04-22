use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use time::OffsetDateTime;
use uuid::Uuid;

use crate::token::InvalidTokenReason;

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum CaptureResponseCode {
    Ok = 1,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct CaptureResponse {
    pub status: CaptureResponseCode,
}

#[derive(Error, Debug)]
pub enum CaptureError {
    #[error("failed to decode request: {0}")]
    RequestDecodingError(String),
    #[error("failed to parse request: {0}")]
    RequestParsingError(#[from] serde_json::Error),

    #[error("request holds no event")]
    EmptyBatch,
    #[error("event submitted with an empty event name")]
    MissingEventName,
    #[error("event submitted without a distinct_id")]
    MissingDistinctId,

    #[error("event submitted without an api_key")]
    NoTokenError,
    #[error("batch submitted with inconsistent api_key values")]
    MultipleTokensError,
    #[error("API key is not valid: {0}")]
    TokenValidationError(#[from] InvalidTokenReason),

    #[error("transient error, please retry")]
    RetryableSinkError,
    #[error("maximum event size exceeded")]
    EventTooBig,
    #[error("invalid event could not be processed")]
    NonRetryableSinkError,

    #[error("billing limit reached")]
    BillingLimit,

    #[error("rate limited")]
    RateLimited,
}

impl IntoResponse for CaptureError {
    fn into_response(self) -> Response {
        match self {
            CaptureError::RequestDecodingError(_)
            | CaptureError::RequestParsingError(_)
            | CaptureError::EmptyBatch
            | CaptureError::MissingEventName
            | CaptureError::MissingDistinctId
            | CaptureError::EventTooBig
            | CaptureError::NonRetryableSinkError => (StatusCode::BAD_REQUEST, self.to_string()),

            CaptureError::NoTokenError
            | CaptureError::MultipleTokensError
            | CaptureError::TokenValidationError(_) => (StatusCode::UNAUTHORIZED, self.to_string()),

            CaptureError::RetryableSinkError => (StatusCode::SERVICE_UNAVAILABLE, self.to_string()),

            CaptureError::BillingLimit | CaptureError::RateLimited => {
                (StatusCode::TOO_MANY_REQUESTS, self.to_string())
            }
        }
        .into_response()
    }
}

#[derive(Clone, Default, Debug, Serialize, Eq, PartialEq)]
pub struct ProcessedEvent {
    pub uuid: Uuid,
    pub distinct_id: String,
    pub ip: String,
    pub data: String,
    pub now: String,
    #[serde(with = "time::serde::rfc3339::option")]
    pub sent_at: Option<OffsetDateTime>,
    pub token: String,
}

impl ProcessedEvent {
    pub fn key(&self) -> String {
        format!("{}:{}", self.token, self.distinct_id)
    }
}
