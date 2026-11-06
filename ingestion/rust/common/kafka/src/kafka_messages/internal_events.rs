use std::collections::HashMap;

use super::{deserialize_datetime, serialize_datetime};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct InternalEventEvent {
    pub uuid: String,
    pub event: String,
    pub distinct_id: String,
    pub properties: HashMap<String, Value>,
    #[serde(
        serialize_with = "serialize_datetime",
        deserialize_with = "deserialize_datetime"
    )]
    pub timestamp: DateTime<Utc>,
    pub url: Option<String>,
}

impl InternalEventEvent {
    pub fn new(
        event: impl ToString,
        distinct_id: impl ToString,
        timestamp: DateTime<Utc>,
        url: Option<String>,
    ) -> Self {
        Self {
            event: event.to_string(),
            distinct_id: distinct_id.to_string(),
            uuid: Uuid::now_v7().to_string(),
            properties: HashMap::new(),
            timestamp,
            url,
        }
    }

    pub fn insert_prop<K: Into<String>, P: Serialize>(
        &mut self,
        key: K,
        prop: P,
    ) -> Result<(), serde_json::Error> {
        let as_json = serde_json::to_value(prop)?;
        self.properties.insert(key.into(), as_json);
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct InternalEventPerson {
    pub id: String,
    pub properties: HashMap<String, Value>,
    pub name: Option<String>,
    pub url: Option<String>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct InternalEvent {
    pub team_id: i32,
    pub event: InternalEventEvent,
    pub person: Option<InternalEventPerson>,
}
