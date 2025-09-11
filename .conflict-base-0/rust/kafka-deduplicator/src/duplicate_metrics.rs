use common_types::RawEvent;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet};

/// Metrics for tracking duplicate events
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DuplicateMetrics {
    /// The composite key for this set of duplicates
    pub composite_key: String,

    /// Number of duplicate events for this composite key
    pub duplicate_count: u64,

    /// Number of unique UUIDs that share the same composite key
    pub unique_uuid_count: u64,

    /// All unique UUIDs seen for this composite key
    pub unique_uuids: HashSet<String>,

    /// Whether the properties are identical (after recursive sorting)
    pub properties_identical: bool,

    /// Properties that changed between duplicates
    pub changed_properties: HashSet<String>,

    /// Properties that remained the same
    pub unchanged_properties: HashSet<String>,

    /// Properties similarity score (0.0 to 1.0)
    pub properties_similarity_score: f64,

    /// First seen timestamp for this composite key
    pub first_seen: u64,

    /// Last seen timestamp for this composite key
    pub last_seen: u64,
}

impl DuplicateMetrics {
    /// Create new metrics for a composite key
    pub fn new(composite_key: String, timestamp: u64) -> Self {
        Self {
            composite_key,
            duplicate_count: 0,
            unique_uuid_count: 0,
            unique_uuids: HashSet::new(),
            properties_identical: true,
            changed_properties: HashSet::new(),
            unchanged_properties: HashSet::new(),
            properties_similarity_score: 1.0,
            first_seen: timestamp,
            last_seen: timestamp,
        }
    }

    /// Update metrics with a new duplicate RawEvent
    pub fn update_with_raw_event(
        &mut self,
        new_event: &RawEvent,
        original_event: &RawEvent,
        timestamp: u64,
    ) {
        self.duplicate_count += 1;
        self.last_seen = timestamp;

        // Track unique UUIDs
        if let Some(new_uuid) = &new_event.uuid {
            let uuid_str = new_uuid.to_string();
            if self.unique_uuids.insert(uuid_str) {
                self.unique_uuid_count += 1;
            }
        }

        // Compare properties with recursive sorting
        let properties_match =
            normalize_and_compare_properties(&original_event.properties, &new_event.properties);
        if !properties_match {
            self.properties_identical = false;
        }

        // Calculate properties similarity and track changes
        self.properties_similarity_score =
            calculate_properties_similarity(&original_event.properties, &new_event.properties);

        // Track changed and unchanged properties
        for (key, orig_value) in &original_event.properties {
            if let Some(new_value) = new_event.properties.get(key) {
                if orig_value == new_value {
                    self.unchanged_properties.insert(key.clone());
                } else {
                    self.changed_properties.insert(key.clone());
                    self.unchanged_properties.remove(key);
                }
            } else {
                // Property removed in new event
                self.changed_properties.insert(key.clone());
                self.unchanged_properties.remove(key);
            }
        }

        // Check for new properties
        for key in new_event.properties.keys() {
            if !original_event.properties.contains_key(key) {
                self.changed_properties.insert(key.clone());
            }
        }
    }

    /// Get a summary of the metrics
    pub fn summary(&self) -> String {
        format!(
            "Composite key: {} | Duplicates: {} | Unique UUIDs: {} | Properties identical: {} | Properties similarity: {:.2} | Changed properties: {} | Unchanged properties: {}",
            self.composite_key,
            self.duplicate_count,
            self.unique_uuid_count,
            self.properties_identical,
            self.properties_similarity_score,
            self.changed_properties.len(),
            self.unchanged_properties.len()
        )
    }
}

/// Normalize and compare properties recursively with sorting
fn normalize_and_compare_properties(
    props1: &HashMap<String, Value>,
    props2: &HashMap<String, Value>,
) -> bool {
    // Normalize both property maps by recursively sorting
    let normalized1 = normalize_json_value(&serde_json::to_value(props1).unwrap_or(Value::Null));
    let normalized2 = normalize_json_value(&serde_json::to_value(props2).unwrap_or(Value::Null));

    normalized1 == normalized2
}

/// Recursively normalize JSON values by sorting objects
fn normalize_json_value(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut sorted_map = serde_json::Map::new();
            let mut keys: Vec<_> = map.keys().collect();
            keys.sort();

            for key in keys {
                if let Some(val) = map.get(key) {
                    sorted_map.insert(key.clone(), normalize_json_value(val));
                }
            }
            Value::Object(sorted_map)
        }
        Value::Array(arr) => {
            // For arrays, we normalize each element but preserve order
            // since array order typically matters for events
            let normalized: Vec<Value> = arr.iter().map(normalize_json_value).collect();
            Value::Array(normalized)
        }
        _ => value.clone(),
    }
}

/// Calculate similarity between two property HashMaps
fn calculate_properties_similarity(
    props1: &HashMap<String, Value>,
    props2: &HashMap<String, Value>,
) -> f64 {
    if props1.is_empty() && props2.is_empty() {
        return 1.0;
    }

    let all_keys: HashSet<_> = props1.keys().chain(props2.keys()).collect();
    let total_keys = all_keys.len();

    if total_keys == 0 {
        return 1.0;
    }

    let mut matching_values = 0;

    for key in all_keys {
        match (props1.get(key), props2.get(key)) {
            (Some(v1), Some(v2)) if v1 == v2 => matching_values += 1,
            _ => {}
        }
    }

    matching_values as f64 / total_keys as f64
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_types::RawEvent;
    use serde_json::json;
    use std::collections::HashMap;
    use uuid::Uuid;

    fn create_test_raw_event(
        uuid: Option<Uuid>,
        event: &str,
        distinct_id: &str,
        token: &str,
        properties: HashMap<String, Value>,
    ) -> RawEvent {
        RawEvent {
            uuid,
            event: event.to_string(),
            distinct_id: Some(json!(distinct_id)),
            token: Some(token.to_string()),
            properties,
            timestamp: Some("1640995200".to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_duplicate_metrics_creation() {
        let metrics = DuplicateMetrics::new("test_key".to_string(), 1640995200);

        assert_eq!(metrics.composite_key, "test_key");
        assert_eq!(metrics.duplicate_count, 0);
        assert_eq!(metrics.unique_uuid_count, 0);
        assert!(metrics.unique_uuids.is_empty());
        assert!(metrics.properties_identical);
        assert!(metrics.changed_properties.is_empty());
        assert!(metrics.unchanged_properties.is_empty());
        assert_eq!(metrics.properties_similarity_score, 1.0);
        assert_eq!(metrics.first_seen, 1640995200);
        assert_eq!(metrics.last_seen, 1640995200);
    }

    #[test]
    fn test_update_with_raw_event_identical_properties() {
        let mut metrics = DuplicateMetrics::new("test_key".to_string(), 1640995200);

        let mut properties = HashMap::new();
        properties.insert("url".to_string(), json!("/home"));
        properties.insert("referrer".to_string(), json!("google"));

        let original_event = create_test_raw_event(
            Some(Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap()),
            "page_view",
            "user1",
            "token1",
            properties.clone(),
        );

        let duplicate_event = create_test_raw_event(
            Some(Uuid::parse_str("550e8400-e29b-41d4-a716-446655440001").unwrap()),
            "page_view",
            "user1",
            "token1",
            properties,
        );

        metrics.update_with_raw_event(&duplicate_event, &original_event, 1640995300);

        assert_eq!(metrics.duplicate_count, 1);
        assert_eq!(metrics.unique_uuid_count, 1);
        assert!(metrics
            .unique_uuids
            .contains("550e8400-e29b-41d4-a716-446655440001"));
        assert!(metrics.properties_identical);
        assert_eq!(metrics.properties_similarity_score, 1.0);
        assert_eq!(metrics.unchanged_properties.len(), 2);
        assert!(metrics.unchanged_properties.contains("url"));
        assert!(metrics.unchanged_properties.contains("referrer"));
        assert!(metrics.changed_properties.is_empty());
        assert_eq!(metrics.last_seen, 1640995300);
    }

    #[test]
    fn test_update_with_raw_event_different_properties() {
        let mut metrics = DuplicateMetrics::new("test_key".to_string(), 1640995200);

        let mut original_props = HashMap::new();
        original_props.insert("url".to_string(), json!("/home"));
        original_props.insert("referrer".to_string(), json!("google"));

        let mut duplicate_props = HashMap::new();
        duplicate_props.insert("url".to_string(), json!("/home")); // Same
        duplicate_props.insert("referrer".to_string(), json!("bing")); // Different
        duplicate_props.insert("campaign".to_string(), json!("summer")); // New property

        let original_event = create_test_raw_event(
            Some(Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap()),
            "page_view",
            "user1",
            "token1",
            original_props,
        );

        let duplicate_event = create_test_raw_event(
            Some(Uuid::parse_str("550e8400-e29b-41d4-a716-446655440001").unwrap()),
            "page_view",
            "user1",
            "token1",
            duplicate_props,
        );

        metrics.update_with_raw_event(&duplicate_event, &original_event, 1640995300);

        assert_eq!(metrics.duplicate_count, 1);
        assert_eq!(metrics.unique_uuid_count, 1);
        assert!(!metrics.properties_identical); // Properties differ
        assert!(metrics.properties_similarity_score < 1.0);

        // Check property tracking
        assert!(metrics.unchanged_properties.contains("url"));
        assert!(metrics.changed_properties.contains("referrer"));
        assert!(metrics.changed_properties.contains("campaign")); // New property
    }

    #[test]
    fn test_update_with_multiple_duplicates() {
        let mut metrics = DuplicateMetrics::new("test_key".to_string(), 1640995200);

        let mut properties = HashMap::new();
        properties.insert("url".to_string(), json!("/home"));

        let original_event = create_test_raw_event(
            Some(Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap()),
            "page_view",
            "user1",
            "token1",
            properties.clone(),
        );

        // First duplicate with different UUID
        let duplicate1 = create_test_raw_event(
            Some(Uuid::parse_str("550e8400-e29b-41d4-a716-446655440001").unwrap()),
            "page_view",
            "user1",
            "token1",
            properties.clone(),
        );

        // Second duplicate with same UUID as first duplicate (shouldn't increase unique count)
        let duplicate2 = create_test_raw_event(
            Some(Uuid::parse_str("550e8400-e29b-41d4-a716-446655440001").unwrap()),
            "page_view",
            "user1",
            "token1",
            properties.clone(),
        );

        // Third duplicate with another new UUID
        let duplicate3 = create_test_raw_event(
            Some(Uuid::parse_str("550e8400-e29b-41d4-a716-446655440002").unwrap()),
            "page_view",
            "user1",
            "token1",
            properties,
        );

        metrics.update_with_raw_event(&duplicate1, &original_event, 1640995300);
        metrics.update_with_raw_event(&duplicate2, &original_event, 1640995400);
        metrics.update_with_raw_event(&duplicate3, &original_event, 1640995500);

        assert_eq!(metrics.duplicate_count, 3);
        assert_eq!(metrics.unique_uuid_count, 2); // Only 2 unique UUIDs from duplicates
        assert!(metrics
            .unique_uuids
            .contains("550e8400-e29b-41d4-a716-446655440001"));
        assert!(metrics
            .unique_uuids
            .contains("550e8400-e29b-41d4-a716-446655440002"));
        assert_eq!(metrics.last_seen, 1640995500);
    }

    #[test]
    fn test_update_with_no_uuid() {
        let mut metrics = DuplicateMetrics::new("test_key".to_string(), 1640995200);

        let mut properties = HashMap::new();
        properties.insert("url".to_string(), json!("/home"));

        let original_event =
            create_test_raw_event(None, "page_view", "user1", "token1", properties.clone());
        let duplicate_event =
            create_test_raw_event(None, "page_view", "user1", "token1", properties);

        metrics.update_with_raw_event(&duplicate_event, &original_event, 1640995300);

        assert_eq!(metrics.duplicate_count, 1);
        assert_eq!(metrics.unique_uuid_count, 0); // No UUIDs to track
        assert!(metrics.unique_uuids.is_empty());
        assert!(metrics.properties_identical);
    }

    #[test]
    fn test_normalize_json_value() {
        // Test object normalization (key sorting)
        let obj1 = json!({
            "z": "last",
            "a": "first",
            "m": "middle"
        });

        let obj2 = json!({
            "a": "first",
            "m": "middle",
            "z": "last"
        });

        let normalized1 = normalize_json_value(&obj1);
        let normalized2 = normalize_json_value(&obj2);
        assert_eq!(normalized1, normalized2);

        // Test nested object normalization
        let nested1 = json!({
            "outer": {
                "z": "last",
                "a": "first"
            }
        });

        let nested2 = json!({
            "outer": {
                "a": "first",
                "z": "last"
            }
        });

        let normalized_nested1 = normalize_json_value(&nested1);
        let normalized_nested2 = normalize_json_value(&nested2);
        assert_eq!(normalized_nested1, normalized_nested2);
    }

    #[test]
    fn test_normalize_and_compare_properties() {
        let mut props1 = HashMap::new();
        props1.insert(
            "nested".to_string(),
            json!({
                "z": "last",
                "a": "first"
            }),
        );
        props1.insert("simple".to_string(), json!("value"));

        let mut props2 = HashMap::new();
        props2.insert("simple".to_string(), json!("value"));
        props2.insert(
            "nested".to_string(),
            json!({
                "a": "first",
                "z": "last"
            }),
        );

        assert!(normalize_and_compare_properties(&props1, &props2));

        // Test with different values
        let mut props3 = HashMap::new();
        props3.insert("simple".to_string(), json!("different"));
        props3.insert(
            "nested".to_string(),
            json!({
                "a": "first",
                "z": "last"
            }),
        );

        assert!(!normalize_and_compare_properties(&props1, &props3));
    }

    #[test]
    fn test_properties_similarity_calculation() {
        let mut props1 = HashMap::new();
        props1.insert("same1".to_string(), json!("value1"));
        props1.insert("same2".to_string(), json!("value2"));
        props1.insert("different".to_string(), json!("original"));
        props1.insert("only_in_first".to_string(), json!("unique"));

        let mut props2 = HashMap::new();
        props2.insert("same1".to_string(), json!("value1"));
        props2.insert("same2".to_string(), json!("value2"));
        props2.insert("different".to_string(), json!("changed"));
        props2.insert("only_in_second".to_string(), json!("new"));

        let similarity = calculate_properties_similarity(&props1, &props2);

        // 2 matching out of 5 total unique keys = 0.4
        assert!((similarity - 0.4).abs() < 0.001);
    }

    #[test]
    fn test_summary_formatting() {
        let mut metrics =
            DuplicateMetrics::new("1640995200:user1:token1:page_view".to_string(), 1640995200);
        metrics.duplicate_count = 5;
        metrics.unique_uuid_count = 3;
        metrics.properties_identical = false;
        metrics.properties_similarity_score = 0.75;
        metrics.changed_properties.insert("referrer".to_string());
        metrics.changed_properties.insert("campaign".to_string());
        metrics.unchanged_properties.insert("url".to_string());
        metrics.unchanged_properties.insert("source".to_string());

        let summary = metrics.summary();

        assert!(summary.contains("Composite key: 1640995200:user1:token1:page_view"));
        assert!(summary.contains("Duplicates: 5"));
        assert!(summary.contains("Unique UUIDs: 3"));
        assert!(summary.contains("Properties identical: false"));
        assert!(summary.contains("Properties similarity: 0.75"));
        assert!(summary.contains("Changed properties: 2"));
        assert!(summary.contains("Unchanged properties: 2"));
    }
}
