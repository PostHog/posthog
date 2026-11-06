use serde::{Deserialize, Deserializer};
use time::OffsetDateTime;
use uuid::Uuid;

pub fn empty_string_uuid_is_none<'de, D>(deserializer: D) -> Result<Option<Uuid>, D::Error>
where
    D: Deserializer<'de>,
{
    let opt = Option::<String>::deserialize(deserializer)?;
    match opt {
        None => Ok(None),
        Some(s) if s.is_empty() => Ok(None),
        Some(s) => Uuid::parse_str(&s)
            .map(Some)
            .map_err(serde::de::Error::custom),
    }
}

pub fn empty_datetime_is_none<'de, D>(deserializer: D) -> Result<Option<OffsetDateTime>, D::Error>
where
    D: Deserializer<'de>,
{
    // First, try to deserialize as an Option<String>
    let opt_str = Option::<String>::deserialize(deserializer)?;

    // If None or empty string, return None
    match opt_str {
        None => Ok(None),
        Some(s) if s.is_empty() => Ok(None),
        Some(s) => {
            // Parse the string into an OffsetDateTime
            OffsetDateTime::parse(&s, &time::format_description::well_known::Rfc3339)
                .map(Some)
                .map_err(serde::de::Error::custom)
        }
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use serde::{Deserialize, Serialize};
    use serde_json::Value;
    use uuid::Uuid;

    fn test_deserialize(json: Value) -> Result<Option<Uuid>, serde_json::Error> {
        #[derive(Deserialize)]
        struct TestStruct {
            #[serde(deserialize_with = "empty_string_uuid_is_none")]
            uuid: Option<Uuid>,
        }

        let result: TestStruct = serde_json::from_value(json)?;
        Ok(result.uuid)
    }

    #[test]
    fn test_empty_uuid_string_is_none() {
        let json = serde_json::json!({"uuid": ""});
        let result = test_deserialize(json);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), None);
    }

    #[test]
    fn test_valid_uuid_is_some() {
        let valid_uuid = "550e8400-e29b-41d4-a716-446655440000";
        let json = serde_json::json!({"uuid": valid_uuid});
        let result = test_deserialize(json);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), Some(Uuid::parse_str(valid_uuid).unwrap()));
    }

    #[test]
    fn test_invalid_uuid_is_error() {
        let invalid_uuid = "not-a-uuid";
        let json = serde_json::json!({"uuid": invalid_uuid});
        let result = test_deserialize(json);
        assert!(result.is_err());
    }

    // The following tests mostly exist to ensure the sent_at handling
    // in the event types behaves as we expect
    #[derive(Debug, Default, Deserialize, Serialize)]
    struct TestDateTime {
        #[serde(
            serialize_with = "time::serde::rfc3339::option::serialize",
            deserialize_with = "empty_datetime_is_none",
            skip_serializing_if = "Option::is_none",
            default
        )]
        val: Option<OffsetDateTime>,
    }

    #[test]
    fn empty_string_is_none() {
        let json = r#"{"val": ""}"#;
        let dt: TestDateTime = serde_json::from_str(json).unwrap();
        assert!(dt.val.is_none());
    }

    #[test]
    fn valid_data_is_valid() {
        let json = r#"{"val": "2023-01-01T00:00:00Z"}"#;
        let dt: TestDateTime = serde_json::from_str(json).unwrap();
        assert!(dt.val.is_some());
    }

    #[test]
    fn invalid_data_is_an_error() {
        let json = r#"{"val": "invalid"}"#;
        let res: Result<TestDateTime, serde_json::Error> = serde_json::from_str(json);
        assert!(res.is_err());
    }

    #[test]
    fn no_data_is_none() {
        let json = r#"{"val": null}"#;
        let dt: TestDateTime = serde_json::from_str(json).unwrap();
        assert!(dt.val.is_none());
    }

    #[test]
    fn serialized_data_is_valid() {
        let dt = TestDateTime {
            val: Some(OffsetDateTime::now_utc()),
        };
        let json = serde_json::to_string(&dt).unwrap();
        let deserialized_dt: TestDateTime = serde_json::from_str(&json).unwrap();
        assert_eq!(dt.val, deserialized_dt.val);
    }
}
