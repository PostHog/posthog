use chrono::{DateTime, Datelike, Duration, TimeZone, Timelike, Utc};
use once_cell::sync::Lazy;
use regex::Regex;

// Compile regex once at startup
static RELATIVE_DATE_REGEX: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^-?(?P<number>[0-9]+)(?P<interval>[hdwmy])$").expect("Invalid regex pattern")
});

/// Parse a relative date string like "-3d", "3d", "-3h", etc.
/// Returns None if the string doesn't match the expected format or if the number is too large.
///
/// This implementation matches Python's behavior using relativedelta:
/// - Hours and days use fixed durations
/// - Weeks are 7 days
/// - Months and years use calendar-aware calculations
///
/// # Examples
/// ```
/// use chrono::Utc;
/// use feature_flags::properties::relative_date::parse_relative_date;
///
/// let now = Utc::now();
/// let three_days_ago = parse_relative_date("-3d").unwrap();
/// assert!(three_days_ago < now);
/// ```
pub fn parse_relative_date(date_str: &str) -> Option<DateTime<Utc>> {
    parse_relative_date_with_now(date_str, Utc::now())
}

/// Internal function that takes a specific "now" time for testing
fn parse_relative_date_with_now(date_str: &str, now: DateTime<Utc>) -> Option<DateTime<Utc>> {
    let captures = RELATIVE_DATE_REGEX.captures(date_str)?;

    let number: i64 = captures.name("number")?.as_str().parse().ok()?;
    if number >= 10_000 {
        // Guard against overflow, disallow numbers greater than 10_000
        return None;
    }

    let interval = captures.name("interval")?.as_str();

    match interval {
        "h" => Some(now - Duration::hours(number)),
        "d" => Some(now - Duration::days(number)),
        "w" => Some(now - Duration::weeks(number)),
        "m" => {
            // Calendar-aware month calculation
            let mut result = now;
            for _ in 0..number {
                // Go back one month, preserving the day if possible
                let day = result.day();
                let month = result.month();
                let year = result.year();

                // Calculate previous month
                let (prev_year, prev_month) = if month == 1 {
                    (year - 1, 12)
                } else {
                    (year, month - 1)
                };

                // Get the last day of the previous month
                let last_day = if prev_month == 2 {
                    if prev_year % 4 == 0 && (prev_year % 100 != 0 || prev_year % 400 == 0) {
                        29 // Leap year
                    } else {
                        28 // Non-leap year
                    }
                } else if [4, 6, 9, 11].contains(&prev_month) {
                    30
                } else {
                    31
                };

                // Use the minimum of the original day and the last day of the previous month
                let new_day = day.min(last_day);
                result = Utc
                    .with_ymd_and_hms(
                        prev_year,
                        prev_month,
                        new_day,
                        result.hour(),
                        result.minute(),
                        result.second(),
                    )
                    .unwrap()
                    .with_nanosecond(result.nanosecond())
                    .unwrap();
            }
            Some(result)
        }
        "y" => {
            // Calendar-aware year calculation
            let mut result = now;
            for _ in 0..number {
                let year = result.year() - 1;
                let month = result.month();
                let day = result.day();

                // Handle February 29 in leap years
                let new_day = if month == 2 && day == 29 {
                    if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) {
                        29 // Leap year
                    } else {
                        28 // Non-leap year
                    }
                } else {
                    day
                };

                result = Utc
                    .with_ymd_and_hms(
                        year,
                        month,
                        new_day,
                        result.hour(),
                        result.minute(),
                        result.second(),
                    )
                    .unwrap()
                    .with_nanosecond(result.nanosecond())
                    .unwrap();
            }
            Some(result)
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Utc};
    use test_case::test_case;

    // Helper function to parse relative date with a fixed "now" time
    fn parse_relative_date_fixed(date_str: &str, now: DateTime<Utc>) -> Option<DateTime<Utc>> {
        parse_relative_date_with_now(date_str, now)
    }

    #[test_case("-3d" => true; "negative days")]
    #[test_case("3d" => true; "positive days")]
    #[test_case("-3h" => true; "negative hours")]
    #[test_case("3h" => true; "positive hours")]
    #[test_case("-3w" => true; "negative weeks")]
    #[test_case("3w" => true; "positive weeks")]
    #[test_case("-3m" => true; "negative months")]
    #[test_case("3m" => true; "positive months")]
    #[test_case("-3y" => true; "negative years")]
    #[test_case("3y" => true; "positive years")]
    #[test_case("invalid" => false; "invalid format")]
    #[test_case("3x" => false; "invalid interval")]
    #[test_case("100000d" => false; "too large number")]
    fn test_parse_relative_date_validity(input: &str) -> bool {
        parse_relative_date(input).is_some()
    }

    #[test]
    fn test_invalid_input() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        // Test various invalid inputs
        assert!(parse_relative_date_fixed("1", now).is_none());
        assert!(parse_relative_date_fixed("1x", now).is_none());
        assert!(parse_relative_date_fixed("1.2y", now).is_none());
        assert!(parse_relative_date_fixed("1z", now).is_none());
        assert!(parse_relative_date_fixed("1s", now).is_none());
        assert!(parse_relative_date_fixed("123344000.134m", now).is_none());
        assert!(parse_relative_date_fixed("bazinga", now).is_none());
        assert!(parse_relative_date_fixed("000bello", now).is_none());
        assert!(parse_relative_date_fixed("000hello", now).is_none());

        // Valid inputs with leading zeros
        assert!(parse_relative_date_fixed("000h", now).is_some());
        assert!(parse_relative_date_fixed("1000h", now).is_some());
    }

    #[test]
    fn test_overflow() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert!(parse_relative_date_fixed("1000000h", now).is_none());
        assert!(parse_relative_date_fixed("100000000000000000y", now).is_none());
    }

    #[test]
    fn test_hour_parsing() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1h", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 1, 1, 11, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2h", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 1, 1, 10, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("24h", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 31, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("30h", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 31, 6, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("48h", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 30, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );

        // 24h should equal 1d
        assert_eq!(
            parse_relative_date_fixed("24h", now).unwrap(),
            parse_relative_date_fixed("1d", now).unwrap()
        );
        // 48h should equal 2d
        assert_eq!(
            parse_relative_date_fixed("48h", now).unwrap(),
            parse_relative_date_fixed("2d", now).unwrap()
        );
    }

    #[test]
    fn test_day_parsing() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 31, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 30, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("7d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 25, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("14d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 18, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("30d", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 2, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );

        // 7d should equal 1w
        assert_eq!(
            parse_relative_date_fixed("7d", now).unwrap(),
            parse_relative_date_fixed("1w", now).unwrap()
        );
    }

    #[test]
    fn test_week_parsing() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1w", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 25, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2w", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 18, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("4w", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 4, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("8w", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 11, 6, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );

        // Test month and year relationships
        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_ne!(
            parse_relative_date_fixed("4w", now).unwrap(),
            parse_relative_date_fixed("1m", now).unwrap()
        );
    }

    #[test]
    fn test_month_parsing() {
        // Test from January
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 11, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("4m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 9, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("8m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 5, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );

        // Test year relationships
        assert_eq!(
            parse_relative_date_fixed("1y", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("12m", now).unwrap(),
            parse_relative_date_fixed("1y", now).unwrap()
        );

        // Test from April
        let now = Utc.with_ymd_and_hms(2020, 4, 3, 0, 0, 0).unwrap();

        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 3, 3, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2m", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 2, 3, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("4m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 12, 3, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("8m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 8, 3, 0, 0, 0).unwrap()
        );

        // Test year relationships from April
        assert_eq!(
            parse_relative_date_fixed("1y", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 4, 3, 0, 0, 0).unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("12m", now).unwrap(),
            parse_relative_date_fixed("1y", now).unwrap()
        );
    }

    #[test]
    fn test_year_parsing() {
        let now = Utc
            .with_ymd_and_hms(2020, 1, 1, 12, 1, 20)
            .unwrap()
            .with_nanosecond(134000000)
            .unwrap();

        assert_eq!(
            parse_relative_date_fixed("1y", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("2y", now).unwrap(),
            Utc.with_ymd_and_hms(2018, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("4y", now).unwrap(),
            Utc.with_ymd_and_hms(2016, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
        assert_eq!(
            parse_relative_date_fixed("8y", now).unwrap(),
            Utc.with_ymd_and_hms(2012, 1, 1, 12, 1, 20)
                .unwrap()
                .with_nanosecond(134000000)
                .unwrap()
        );
    }

    #[test]
    fn test_edge_cases() {
        // Test month boundaries
        let now = Utc.with_ymd_and_hms(2020, 3, 31, 12, 0, 0).unwrap();
        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2020, 2, 29, 12, 0, 0).unwrap() // Leap year
        );

        let now = Utc.with_ymd_and_hms(2019, 3, 31, 12, 0, 0).unwrap();
        assert_eq!(
            parse_relative_date_fixed("1m", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 2, 28, 12, 0, 0).unwrap() // Non-leap year
        );

        // Test year boundaries
        let now = Utc.with_ymd_and_hms(2020, 2, 29, 12, 0, 0).unwrap();
        assert_eq!(
            parse_relative_date_fixed("1y", now).unwrap(),
            Utc.with_ymd_and_hms(2019, 2, 28, 12, 0, 0).unwrap() // Non-leap year
        );

        // Test large numbers
        let now = Utc.with_ymd_and_hms(2020, 1, 1, 12, 0, 0).unwrap();
        assert!(parse_relative_date_fixed("9999d", now).is_some());
        assert!(parse_relative_date_fixed("9999h", now).is_some());
        assert!(parse_relative_date_fixed("9999w", now).is_some());
        assert!(parse_relative_date_fixed("9999m", now).is_some());
        assert!(parse_relative_date_fixed("9999y", now).is_some());
    }
}
