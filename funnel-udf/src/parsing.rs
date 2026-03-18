use serde::{Deserialize, Deserializer};
use std::str::FromStr;

#[derive(Deserialize)]
#[serde(untagged)]
enum U64OrString {
    U64(u64),
    String(String),
}

pub fn u64_or_string<'de, D>(deserializer: D) -> Result<u64, D::Error>
where
    D: Deserializer<'de>,
{
    match U64OrString::deserialize(deserializer)? {
        U64OrString::U64(v) => Ok(v),
        U64OrString::String(v) => u64::from_str(&v).map_err(serde::de::Error::custom),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde::Deserialize;

    #[derive(Deserialize)]
    struct TestStruct {
        #[serde(deserialize_with = "u64_or_string")]
        value: u64,
    }

    #[rstest]
    #[case(r#"{"value": 0}"#, 0)]
    #[case(r#"{"value": 12345}"#, 12345)]
    #[case(r#"{"value": 67890}"#, 67890)]
    #[case(r#"{"value": 18446744073709551615}"#, u64::MAX)]
    #[case(r#"{"value": "0"}"#, 0)]
    #[case(r#"{"value": "12345"}"#, 12345)]
    #[case(r#"{"value": "67890"}"#, 67890)]
    #[case(r#"{"value": "18446744073709551615"}"#, u64::MAX)]
    fn test_deserialize_u64_valid(#[case] json: &str, #[case] expected: u64) {
        let result: TestStruct = serde_json::from_str(json).unwrap();
        assert_eq!(result.value, expected);
    }

    #[rstest]
    #[case(r#"{"value": "not_a_number"}"#)]
    #[case(r#"{"value": "-123"}"#)]
    #[case(r#"{"value": ""}"#)]
    #[case(r#"{"value": "18446744073709551616"}"#)] // u64::MAX + 1
    #[case(r#"{"value": "12.34"}"#)]
    #[case(r#"{"value": "  123  "}"#)]
    fn test_deserialize_u64_invalid(#[case] json: &str) {
        let result: Result<TestStruct, _> = serde_json::from_str(json);
        assert!(result.is_err());
    }
}
