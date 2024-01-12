use chrono::{DateTime, Utc};
use serde::{Serialize, Serializer};
use uuid::Uuid;

use super::serialize_datetime;

#[allow(dead_code)]
#[derive(Serialize)]
pub enum PluginLogEntrySource {
    System,
    Plugin,
    Console,
}

#[allow(dead_code)]
#[derive(Serialize)]
pub enum PluginLogEntryType {
    Debug,
    Log,
    Info,
    Warn,
    Error,
}

#[derive(Serialize)]
pub struct PluginLogEntry {
    #[serde(serialize_with = "serialize_source")]
    pub source: PluginLogEntrySource,
    #[serde(rename = "type", serialize_with = "serialize_type")]
    pub type_: PluginLogEntryType,
    pub id: Uuid,
    pub team_id: u32,
    pub plugin_id: i32,
    pub plugin_config_id: i32,
    #[serde(serialize_with = "serialize_datetime")]
    pub timestamp: DateTime<Utc>,
    #[serde(serialize_with = "serialize_message")]
    pub message: String,
    pub instance_id: Uuid,
}

fn serialize_source<S>(source: &PluginLogEntrySource, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    let source_str = match source {
        PluginLogEntrySource::System => "SYSTEM",
        PluginLogEntrySource::Plugin => "PLUGIN",
        PluginLogEntrySource::Console => "CONSOLE",
    };
    serializer.serialize_str(source_str)
}

fn serialize_type<S>(type_: &PluginLogEntryType, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    let type_str = match type_ {
        PluginLogEntryType::Debug => "DEBUG",
        PluginLogEntryType::Log => "LOG",
        PluginLogEntryType::Info => "INFO",
        PluginLogEntryType::Warn => "WARN",
        PluginLogEntryType::Error => "ERROR",
    };
    serializer.serialize_str(type_str)
}

fn serialize_message<S>(msg: &String, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    if msg.len() > 50_000 {
        return Err(serde::ser::Error::custom(
            "Message is too long for ClickHouse",
        ));
    }

    serializer.serialize_str(msg)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_plugin_log_entry_serialization() {
        use chrono::prelude::*;

        let log_entry = PluginLogEntry {
            source: PluginLogEntrySource::Plugin,
            type_: PluginLogEntryType::Warn,
            id: Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            team_id: 4,
            plugin_id: 5,
            plugin_config_id: 6,
            timestamp: Utc.with_ymd_and_hms(2023, 12, 14, 12, 2, 0).unwrap(),
            message: "My message!".to_string(),
            instance_id: Uuid::parse_str("00000000-0000-0000-0000-000000000000").unwrap(),
        };

        let serialized_json = serde_json::to_string(&log_entry).unwrap();

        assert_eq!(
            serialized_json,
            r#"{"source":"PLUGIN","type":"WARN","id":"550e8400-e29b-41d4-a716-446655440000","team_id":4,"plugin_id":5,"plugin_config_id":6,"timestamp":"2023-12-14 12:02:00","message":"My message!","instance_id":"00000000-0000-0000-0000-000000000000"}"#
        );
    }

    #[test]
    fn test_plugin_log_entry_message_too_long() {
        use chrono::prelude::*;

        let log_entry = PluginLogEntry {
            source: PluginLogEntrySource::Plugin,
            type_: PluginLogEntryType::Warn,
            id: Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap(),
            team_id: 4,
            plugin_id: 5,
            plugin_config_id: 6,
            timestamp: Utc.with_ymd_and_hms(2023, 12, 14, 12, 2, 0).unwrap(),
            message: "My message!".repeat(10_000).to_string(),
            instance_id: Uuid::parse_str("00000000-0000-0000-0000-000000000000").unwrap(),
        };

        let err = serde_json::to_string(&log_entry).unwrap_err();
        assert_eq!(err.to_string(), "Message is too long for ClickHouse");
    }
}
