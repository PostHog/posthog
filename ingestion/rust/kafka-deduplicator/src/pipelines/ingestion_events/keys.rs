//! Deduplication key extraction for ingestion events.

use common_types::RawEvent;

use crate::pipelines::traits::DeduplicationKeyExtractor;
use crate::store::keys::TimestampKey;

impl DeduplicationKeyExtractor for RawEvent {
    fn extract_dedup_key(&self) -> Vec<u8> {
        let key = TimestampKey::from(self);
        (&key).into()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn create_test_event() -> RawEvent {
        RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user123".to_string())),
            token: Some("token456".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_raw_event_dedup_key_extraction() {
        let event = create_test_event();
        let key_bytes = event.extract_dedup_key();

        // Key should be non-empty
        assert!(!key_bytes.is_empty());

        // Should be at least 8 bytes (timestamp) plus some data
        assert!(key_bytes.len() > 8);
    }

    #[test]
    fn test_same_event_produces_same_key() {
        let event1 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()), // Different UUID
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        // Same dedup key despite different UUIDs
        assert_eq!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_different_events_produce_different_keys() {
        let event1 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "button_click".to_string(), // Different event name
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        assert_ne!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_event_with_none_token_produces_valid_key() {
        let event = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: None, // No token
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let key = event.extract_dedup_key();
        assert!(!key.is_empty());
    }

    #[test]
    fn test_event_with_none_distinct_id_produces_valid_key() {
        let event = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: None, // No distinct_id
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let key = event.extract_dedup_key();
        assert!(!key.is_empty());
    }

    #[test]
    fn test_event_with_json_null_distinct_id_produces_valid_key() {
        let event = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::Null), // JSON null
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let key = event.extract_dedup_key();
        assert!(!key.is_empty());
    }

    #[test]
    fn test_event_with_none_timestamp_produces_valid_key() {
        let event = RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: HashMap::new(),
            timestamp: None, // No timestamp
            ..Default::default()
        };

        let key = event.extract_dedup_key();
        assert!(!key.is_empty());
    }

    #[test]
    fn test_event_with_all_optional_fields_none() {
        let event = RawEvent {
            uuid: None,
            event: "test_event".to_string(),
            distinct_id: None,
            token: None,
            properties: HashMap::new(),
            timestamp: None,
            ..Default::default()
        };

        let key = event.extract_dedup_key();
        assert!(!key.is_empty());
    }

    #[test]
    fn test_different_distinct_id_types_produce_different_keys() {
        // String distinct_id
        let event1 = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        // Numeric distinct_id (same value as string)
        let event2 = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::json!(1)), // Number 1
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        // Different types should produce different keys
        assert_ne!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }

    #[test]
    fn test_different_timestamps_produce_different_keys() {
        let event1 = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            timestamp: Some("2024-01-01T00:00:01Z".to_string()), // 1 second later
            ..Default::default()
        };

        assert_ne!(event1.extract_dedup_key(), event2.extract_dedup_key());
    }
}
