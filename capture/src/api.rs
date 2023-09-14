use crate::token::InvalidTokenReason;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use thiserror::Error;

#[derive(Debug, Deserialize, Serialize)]
pub struct CaptureRequest {
    #[serde(alias = "$token", alias = "api_key")]
    pub token: String,

    pub event: String,
    pub properties: HashMap<String, Value>,
}

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
    #[error("failed to decode request: {0}")]
    RequestParsingError(#[from] serde_json::Error),

    #[error("request holds no event")]
    EmptyBatch,
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
}

impl IntoResponse for CaptureError {
    fn into_response(self) -> Response {
        match self {
            CaptureError::RequestDecodingError(_)
            | CaptureError::RequestParsingError(_)
            | CaptureError::EmptyBatch
            | CaptureError::MissingDistinctId
            | CaptureError::EventTooBig
            | CaptureError::NonRetryableSinkError => (StatusCode::BAD_REQUEST, self.to_string()),
            CaptureError::NoTokenError
            | CaptureError::MultipleTokensError
            | CaptureError::TokenValidationError(_) => (StatusCode::UNAUTHORIZED, self.to_string()),
            CaptureError::RetryableSinkError => (StatusCode::SERVICE_UNAVAILABLE, self.to_string()),
        }
        .into_response()
    }
}
