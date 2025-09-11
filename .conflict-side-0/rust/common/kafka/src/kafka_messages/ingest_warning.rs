use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Clone, Serialize)]
pub struct IngestionWarning {
    pub team_id: i32,
    pub source: String,
    #[serde(rename = "type")]
    pub warning_type: String,
    pub details: String,
    #[serde(serialize_with = "super::serialize_datetime")]
    pub timestamp: DateTime<Utc>, // CH formatted timestamp
}

impl IngestionWarning {
    pub fn new(
        team_id: i32,
        source: String,
        warning_type: String,
        details: HashMap<String, Value>,
        timestamp: Option<DateTime<Utc>>,
    ) -> Self {
        let timestamp = timestamp.unwrap_or_else(Utc::now);
        let details = serde_json::to_string(&details).expect("Failed to serialize details");
        Self {
            team_id,
            source,
            warning_type,
            details,
            timestamp,
        }
    }
}
