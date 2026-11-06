/// Parse a timestamp string into milliseconds since epoch
/// Supports only valid formats:
/// - u64 (assumed to be milliseconds or seconds based on magnitude)
/// - ISO 8601 / RFC3339 datetime strings (strict format)
/// - ClickHouse DateTime64 format: "2024-01-01 12:00:00.000000" (assumed UTC)
pub fn parse_timestamp(timestamp_str: &str) -> Option<u64> {
    // First try parsing as u64 (for backward compatibility with numeric timestamps)
    if let Ok(ts) = timestamp_str.parse::<u64>() {
        // If it's a 10-digit number, assume it's seconds and convert to millis
        // If it's 13+ digits, assume it's already milliseconds
        if ts < 10_000_000_000 {
            return Some(ts * 1000);
        } else {
            return Some(ts);
        }
    }

    // Try parsing as ISO 8601 / RFC3339 datetime (strict format)
    if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(timestamp_str) {
        // Convert to milliseconds for consistent precision
        return Some(dt.timestamp_millis() as u64);
    }

    // Try parsing as ClickHouse DateTime64 format: "2024-01-01 12:00:00.000000"
    // This format doesn't include timezone, so we assume UTC
    if let Some(millis) = parse_clickhouse_timestamp(timestamp_str) {
        return Some(millis);
    }

    // Not a valid timestamp format
    None
}

/// Parse ClickHouse DateTime64 format: "2024-01-01 12:00:00.000000"
/// Returns milliseconds since epoch (assumes UTC)
pub fn parse_clickhouse_timestamp(timestamp_str: &str) -> Option<u64> {
    use chrono::NaiveDateTime;

    // ClickHouse DateTime64(6) format: "2024-01-01 12:00:00.000000"
    // Also handles: "2024-01-01 12:00:00" (no microseconds)
    let formats = ["%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%d %H:%M:%S"];

    for fmt in formats {
        if let Ok(naive) = NaiveDateTime::parse_from_str(timestamp_str, fmt) {
            // Assume UTC and convert to milliseconds
            return Some(naive.and_utc().timestamp_millis() as u64);
        }
    }

    None
}

/// Check if a timestamp string is in a valid format
pub fn is_valid_timestamp(timestamp_str: &str) -> bool {
    parse_timestamp(timestamp_str).is_some()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_timestamp_valid_formats() {
        // Test standard RFC3339 formats
        assert!(parse_timestamp("2025-09-02T14:45:58.462+02:00").is_some());
        assert!(parse_timestamp("2025-09-02T14:45:58.462Z").is_some());
        assert!(parse_timestamp("2025-09-02T14:45:58+02:00").is_some());

        // Test numeric timestamps
        assert_eq!(parse_timestamp("1693584358"), Some(1693584358000)); // seconds to millis
        assert_eq!(parse_timestamp("1693584358000"), Some(1693584358000)); // already millis
    }

    #[test]
    fn test_parse_timestamp_invalid_formats() {
        // These formats are not valid RFC3339 and should fail
        assert!(parse_timestamp("2025-09-02T14:45:58.462+02").is_none()); // Missing :00

        // Other invalid formats
        assert!(parse_timestamp("not-a-timestamp").is_none());
        assert!(parse_timestamp("").is_none());
    }

    #[test]
    fn test_is_valid_timestamp() {
        // Valid formats
        assert!(is_valid_timestamp("2025-09-02T14:45:58.462+02:00"));
        assert!(is_valid_timestamp("2025-09-02T14:45:58.462Z"));
        assert!(is_valid_timestamp("1693584358"));

        // Invalid formats
        assert!(!is_valid_timestamp("2025-09-02T14:45:58.462+02")); // Missing :00
        assert!(!is_valid_timestamp("not-a-timestamp"));
        assert!(!is_valid_timestamp(""));
    }

    #[test]
    fn test_parse_clickhouse_timestamp_with_microseconds() {
        // ClickHouse DateTime64(6) format
        let result = parse_clickhouse_timestamp("2024-01-01 12:00:00.000000");
        assert!(result.is_some());
        // 2024-01-01 12:00:00 UTC = 1704110400000 ms
        assert_eq!(result.unwrap(), 1704110400000);
    }

    #[test]
    fn test_parse_clickhouse_timestamp_with_partial_microseconds() {
        // ClickHouse may have varying precision
        assert!(parse_clickhouse_timestamp("2024-01-01 12:00:00.123").is_some());
        assert!(parse_clickhouse_timestamp("2024-01-01 12:00:00.123456").is_some());
    }

    #[test]
    fn test_parse_clickhouse_timestamp_without_microseconds() {
        let result = parse_clickhouse_timestamp("2024-01-01 12:00:00");
        assert!(result.is_some());
        assert_eq!(result.unwrap(), 1704110400000);
    }

    #[test]
    fn test_parse_clickhouse_timestamp_invalid() {
        assert!(parse_clickhouse_timestamp("2024-01-01T12:00:00").is_none()); // T separator
        assert!(parse_clickhouse_timestamp("not-a-timestamp").is_none());
        assert!(parse_clickhouse_timestamp("").is_none());
    }

    #[test]
    fn test_parse_timestamp_accepts_clickhouse_format() {
        // The main parse_timestamp function should also accept ClickHouse format
        assert!(parse_timestamp("2024-01-01 12:00:00.000000").is_some());
        assert!(parse_timestamp("2024-01-01 12:00:00").is_some());
    }

    #[test]
    fn test_clickhouse_timestamp_consistency() {
        // Same timestamp in different formats should produce same milliseconds
        let clickhouse = parse_timestamp("2024-01-01 12:00:00.000000").unwrap();
        let rfc3339 = parse_timestamp("2024-01-01T12:00:00.000Z").unwrap();
        assert_eq!(clickhouse, rfc3339);
    }
}
