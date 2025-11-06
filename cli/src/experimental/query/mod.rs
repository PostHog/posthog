use std::collections::HashMap;

use anyhow::Error;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::invocation_context::context;

pub mod command;

// TODO - we could formalise a lot of this and move it into posthog-rs, tbh

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryRequest {
    pub query: Query,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub refresh: Option<QueryRefresh>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Query {
    HogQLQuery { query: String },
    HogQLMetadata(MetadataQuery),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QueryRefresh {
    Blocking,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetadataQuery {
    pub language: MetadataLanguage,
    pub query: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<Box<Query>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum MetadataLanguage {
    #[serde(rename = "hogQL")]
    HogQL,
}

pub type HogQLQueryResult = Result<HogQLQueryResponse, HogQLQueryErrorResponse>;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HogQLQueryResponse {
    pub cache_key: Option<String>,
    pub cache_target_age: Option<String>,
    pub clickhouse: Option<String>, // Clickhouse query text
    #[serde(default, deserialize_with = "null_is_empty")]
    pub columns: Vec<String>, // Columns returned from the query
    pub error: Option<String>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub explain: Vec<String>,
    #[serde(default, rename = "hasMore", deserialize_with = "null_is_false")]
    pub has_more: bool,
    pub hogql: Option<String>, // HogQL query text
    #[serde(default, deserialize_with = "null_is_false")]
    pub is_cached: bool,
    pub last_refresh: Option<String>, // Last time the query was refreshed
    pub next_allowed_client_refresh_time: Option<String>, // Next time the client can refresh the query
    pub offset: Option<i64>,                              // Offset of the response rows
    pub limit: Option<i64>,                               // Limit of the query
    pub query: Option<String>,                            // Query text
    #[serde(default, deserialize_with = "null_is_empty")]
    pub types: Vec<(String, String)>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub results: Vec<Vec<Value>>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub timings: Vec<Timing>,
    #[serde(flatten, skip_serializing_if = "HashMap::is_empty")]
    pub other: HashMap<String, Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HogQLQueryErrorResponse {
    pub code: String,
    pub detail: String,
    #[serde(rename = "type")]
    pub error_type: String,
    #[serde(flatten, skip_serializing_if = "HashMap::is_empty")]
    pub other: HashMap<String, Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Timing {
    pub k: String,
    pub t: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct MetadataResponse {
    #[serde(default, deserialize_with = "null_is_empty")]
    pub errors: Vec<Notice>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub notices: Vec<Notice>,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub warnings: Vec<Notice>,
    #[serde(default, rename = "isUsingIndices")]
    pub is_using_indices: Option<IndicesUsage>,
    #[serde(default, deserialize_with = "null_is_false", rename = "isValid")]
    pub is_valid: bool,
    #[serde(default, deserialize_with = "null_is_false")]
    pub is_valid_view: bool,
    #[serde(default, deserialize_with = "null_is_empty")]
    pub table_names: Vec<String>,
    #[serde(flatten, skip_serializing_if = "HashMap::is_empty")]
    pub other: HashMap<String, Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum IndicesUsage {
    Undecisive,
    No,
    Partial,
    Yes,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Notice {
    pub message: String,
    #[serde(flatten)]
    pub span: Option<NoticeSpan>,
    #[serde(flatten, skip_serializing_if = "HashMap::is_empty")]
    pub other: HashMap<String, Value>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct NoticeSpan {
    pub start: usize,
    pub end: usize,
}

fn null_is_empty<'de, D, T>(deserializer: D) -> Result<Vec<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: serde::Deserialize<'de>,
{
    let opt = Option::deserialize(deserializer)?;
    match opt {
        Some(v) => Ok(v),
        None => Ok(Vec::new()),
    }
}

fn null_is_false<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let opt = Option::deserialize(deserializer)?;
    match opt {
        Some(v) => Ok(v),
        None => Ok(false),
    }
}

pub fn run_query(to_run: &str) -> Result<HogQLQueryResult, Error> {
    let client = &context().client;
    let request = QueryRequest {
        query: Query::HogQLQuery {
            query: to_run.to_string(),
        },
        refresh: Some(QueryRefresh::Blocking),
    };

    let response = client.post("query").json(&request).send()?;

    let code = response.status();
    let body = response.text()?;

    let value: Value = serde_json::from_str(&body)?;

    if !code.is_success() {
        let error: HogQLQueryErrorResponse = serde_json::from_value(value)?;
        return Ok(Err(error));
    }

    // NOTE: We don't do any pagination here, because the HogQLQuery runner doesn't support it
    let response: HogQLQueryResponse = serde_json::from_value(value)?;
    Ok(Ok(response))
}

pub fn check_query(to_run: &str) -> Result<MetadataResponse, Error> {
    let client = &context().client;

    let query = MetadataQuery {
        language: MetadataLanguage::HogQL,
        query: to_run.to_string(),
        source: None, // TODO - allow for this to be set? Idk if it matters much
    };

    let query = Query::HogQLMetadata(query);

    let request = QueryRequest {
        query,
        refresh: None,
    };

    let response = client.post("query").json(&request).send()?;

    let code = response.status();
    let body = response.text()?;

    let value: Value = serde_json::from_str(&body)?;

    if !code.is_success() {
        let error: MetadataResponse = serde_json::from_value(value)?;
        return Ok(error);
    }

    let response: MetadataResponse = serde_json::from_value(value)?;

    Ok(response)
}

impl std::error::Error for HogQLQueryErrorResponse {}

impl std::fmt::Display for HogQLQueryErrorResponse {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} ({}): {}", self.error_type, self.code, self.detail)
    }
}
