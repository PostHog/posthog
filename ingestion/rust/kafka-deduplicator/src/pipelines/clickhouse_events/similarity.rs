//! Similarity calculation for ClickHouseEvent.

use std::collections::HashMap;

use anyhow::Result;
use common_types::ClickHouseEvent;

use crate::pipelines::results::{EventSimilarity, SimilarityComparable};

impl SimilarityComparable for ClickHouseEvent {
    fn calculate_similarity(original: &Self, new: &Self) -> Result<EventSimilarity> {
        let mut different_fields = Vec::new();
        let mut matching_fields = 0u32;
        let total_fields = 6u32; // uuid, team_id, event, distinct_id, timestamp, person_id

        // Compare UUID
        if original.uuid == new.uuid {
            matching_fields += 1;
        } else {
            different_fields.push((
                "uuid".to_string(),
                original.uuid.to_string(),
                new.uuid.to_string(),
            ));
        }

        // Compare team_id
        if original.team_id == new.team_id {
            matching_fields += 1;
        } else {
            different_fields.push((
                "team_id".to_string(),
                original.team_id.to_string(),
                new.team_id.to_string(),
            ));
        }

        // Compare event name
        if original.event == new.event {
            matching_fields += 1;
        } else {
            different_fields.push((
                "event".to_string(),
                original.event.clone(),
                new.event.clone(),
            ));
        }

        // Compare distinct_id
        if original.distinct_id == new.distinct_id {
            matching_fields += 1;
        } else {
            different_fields.push((
                "distinct_id".to_string(),
                original.distinct_id.clone(),
                new.distinct_id.clone(),
            ));
        }

        // Compare timestamp
        if original.timestamp == new.timestamp {
            matching_fields += 1;
        } else {
            different_fields.push((
                "timestamp".to_string(),
                original.timestamp.clone(),
                new.timestamp.clone(),
            ));
        }

        // Compare person_id
        if original.person_id == new.person_id {
            matching_fields += 1;
        } else {
            different_fields.push((
                "person_id".to_string(),
                format!("{:?}", original.person_id),
                format!("{:?}", new.person_id),
            ));
        }

        // Compare properties (parse JSON strings)
        let original_props = parse_properties(&original.properties);
        let new_props = parse_properties(&new.properties);

        let (properties_similarity, different_properties) =
            EventSimilarity::compare_properties(&original_props, &new_props);

        Ok(EventSimilarity::from_field_comparisons(
            matching_fields,
            total_fields,
            different_fields,
            properties_similarity,
            different_properties,
        ))
    }
}

fn parse_properties(props: &Option<String>) -> HashMap<String, serde_json::Value> {
    props
        .as_ref()
        .and_then(|s| serde_json::from_str(s).ok())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_types::PersonMode;
    use uuid::Uuid;

    fn create_test_event(uuid: Uuid) -> ClickHouseEvent {
        ClickHouseEvent {
            uuid,
            team_id: 123,
            project_id: Some(456),
            event: "test_event".to_string(),
            distinct_id: "user123".to_string(),
            properties: Some(r#"{"key": "value"}"#.to_string()),
            person_id: Some("person-uuid".to_string()),
            timestamp: "2024-01-01 12:00:00.000000".to_string(),
            created_at: "2024-01-01 12:00:00.000000".to_string(),
            captured_at: None,
            elements_chain: None,
            person_created_at: None,
            person_properties: None,
            group0_properties: None,
            group1_properties: None,
            group2_properties: None,
            group3_properties: None,
            group4_properties: None,
            group0_created_at: None,
            group1_created_at: None,
            group2_created_at: None,
            group3_created_at: None,
            group4_created_at: None,
            person_mode: PersonMode::Full,
            historical_migration: None,
        }
    }

    #[test]
    fn test_clickhouse_event_similarity_identical() {
        let uuid = Uuid::new_v4();
        let event1 = create_test_event(uuid);
        let event2 = create_test_event(uuid);

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        assert_eq!(similarity.different_field_count, 0);
        assert_eq!(similarity.different_property_count, 0);
        assert_eq!(similarity.properties_similarity, 1.0);
        assert_eq!(similarity.overall_score, 1.0);
    }

    #[test]
    fn test_clickhouse_event_similarity_only_uuid_differs() {
        let event1 = create_test_event(Uuid::new_v4());
        let event2 = create_test_event(Uuid::new_v4());

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        assert_eq!(similarity.different_field_count, 1);
        assert!(similarity
            .different_fields
            .iter()
            .any(|(field, _, _)| field == "uuid"));
        assert_eq!(similarity.properties_similarity, 1.0);
    }

    #[test]
    fn test_clickhouse_event_similarity_multiple_differences() {
        let mut event1 = create_test_event(Uuid::new_v4());
        let mut event2 = create_test_event(Uuid::new_v4());

        event1.properties = Some(r#"{"url": "/home", "referrer": "google"}"#.to_string());
        event2.properties =
            Some(r#"{"url": "/about", "referrer": "google", "browser": "chrome"}"#.to_string());

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        assert!(similarity.different_field_count >= 1);
        assert_eq!(similarity.different_property_count, 2); // url differs, browser is new
        assert!(similarity.properties_similarity < 1.0);
        assert!(similarity.overall_score < 1.0);
    }
}
