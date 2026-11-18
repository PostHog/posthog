use std::time::Duration;

use reqwest::StatusCode;

/// What to do with one intake response.
#[derive(Debug, Clone, PartialEq)]
pub enum Disposition {
    Accepted,
    /// Wait, then send the same batch again. An import is the one client that reliably saturates
    /// the intake, so backing off is the client's job.
    Retry(Duration),
    /// Sending the same batch again cannot succeed, so the run stops and says why.
    Permanent(String),
}

const DEFAULT_BACKOFF: Duration = Duration::from_secs(5);

/// Decides from the status and `Retry-After` alone, so the whole policy is testable without a
/// server.
pub fn classify(status: StatusCode, retry_after: Option<&str>, attempt: u32) -> Disposition {
    if status.is_success() {
        return Disposition::Accepted;
    }

    match status {
        StatusCode::TOO_MANY_REQUESTS | StatusCode::SERVICE_UNAVAILABLE => {
            Disposition::Retry(parse_retry_after(retry_after).unwrap_or_else(|| backoff(attempt)))
        }
        StatusCode::REQUEST_TIMEOUT | StatusCode::BAD_GATEWAY | StatusCode::GATEWAY_TIMEOUT => {
            Disposition::Retry(backoff(attempt))
        }
        StatusCode::PAYLOAD_TOO_LARGE => Disposition::Permanent(
            "the intake rejected the body as too large. Lower tuning.max_request_bytes to below \
             the deployment's MAX_REQUEST_BODY_SIZE_BYTES."
                .to_string(),
        ),
        StatusCode::UNAUTHORIZED => Disposition::Permanent(
            "the intake rejected the project API key. Check POSTHOG_PROJECT_API_KEY; a personal API \
             token is not accepted."
                .to_string(),
        ),
        StatusCode::BAD_REQUEST => Disposition::Permanent(
            "the intake rejected the request. If the range reaches past the deployment's \
             MAX_BACKFILL_DAYS, backdated logs are not enabled for it."
                .to_string(),
        ),
        other if other.is_server_error() => Disposition::Retry(backoff(attempt)),
        other => Disposition::Permanent(format!("the intake answered {other}")),
    }
}

/// Doubles per attempt and stops at a minute, so a long outage does not turn into a tight loop or
/// an unbounded sleep.
pub fn backoff(attempt: u32) -> Duration {
    let seconds = DEFAULT_BACKOFF
        .as_secs()
        .saturating_mul(1u64 << attempt.min(4));
    Duration::from_secs(seconds.min(60))
}

/// RFC 7231 allows either a delay in seconds or an HTTP date. Only the delay form is honored,
/// because a date form from a skewed clock can produce an enormous sleep.
fn parse_retry_after(header: Option<&str>) -> Option<Duration> {
    let seconds: u64 = header?.trim().parse().ok()?;
    Some(Duration::from_secs(seconds.min(300)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_rate_limit_honors_retry_after_over_the_backoff() {
        let waited = classify(StatusCode::TOO_MANY_REQUESTS, Some("30"), 0);

        assert_eq!(waited, Disposition::Retry(Duration::from_secs(30)));
    }

    #[test]
    fn transient_statuses_retry_and_terminal_ones_stop() {
        // (case, status, expect a retry)
        let cases = [
            ("rate limited", StatusCode::TOO_MANY_REQUESTS, true),
            (
                "the intake is restarting",
                StatusCode::SERVICE_UNAVAILABLE,
                true,
            ),
            ("a gateway timeout", StatusCode::GATEWAY_TIMEOUT, true),
            (
                "an unnamed server error",
                StatusCode::INTERNAL_SERVER_ERROR,
                true,
            ),
            (
                "a body over the limit",
                StatusCode::PAYLOAD_TOO_LARGE,
                false,
            ),
            ("a rejected token", StatusCode::UNAUTHORIZED, false),
            ("backfill not enabled", StatusCode::BAD_REQUEST, false),
            ("a forbidden project", StatusCode::FORBIDDEN, false),
        ];

        for (case, status, expect_retry) in cases {
            let disposition = classify(status, None, 0);

            assert_eq!(
                matches!(disposition, Disposition::Retry(_)),
                expect_retry,
                "{case}: got {disposition:?}"
            );
        }
    }

    #[test]
    fn a_permanent_failure_names_the_setting_that_caused_it() {
        // An import runs unattended for hours, so the message is the only diagnosis its operator gets.
        let cases = [
            (StatusCode::PAYLOAD_TOO_LARGE, "max_request_bytes"),
            (StatusCode::UNAUTHORIZED, "POSTHOG_PROJECT_API_KEY"),
            (StatusCode::BAD_REQUEST, "MAX_BACKFILL_DAYS"),
        ];

        for (status, expected) in cases {
            match classify(status, None, 0) {
                Disposition::Permanent(message) => assert!(
                    message.contains(expected),
                    "expected {status} to mention {expected}, got: {message}"
                ),
                other => panic!("expected {status} to be permanent, got {other:?}"),
            }
        }
    }

    #[test]
    fn backoff_grows_then_stops_growing() {
        // Without the ceiling a long outage sleeps for hours; without the growth it hammers.
        let waits: Vec<u64> = (0..8)
            .map(
                |attempt| match classify(StatusCode::INTERNAL_SERVER_ERROR, None, attempt) {
                    Disposition::Retry(wait) => wait.as_secs(),
                    other => panic!("expected a retry, got {other:?}"),
                },
            )
            .collect();

        assert_eq!(waits, [5, 10, 20, 40, 60, 60, 60, 60]);
    }

    #[test]
    fn an_unusable_retry_after_falls_back_to_the_backoff() {
        // A date-form header from a skewed clock must not become an enormous sleep.
        let cases = ["Wed, 21 Oct 2026 07:28:00 GMT", "", "soon", "-5"];

        for header in cases {
            let disposition = classify(StatusCode::TOO_MANY_REQUESTS, Some(header), 0);

            assert_eq!(
                disposition,
                Disposition::Retry(DEFAULT_BACKOFF),
                "header {header:?} should fall back"
            );
        }
    }

    #[test]
    fn a_huge_retry_after_is_capped() {
        let disposition = classify(StatusCode::TOO_MANY_REQUESTS, Some("86400"), 0);

        assert_eq!(disposition, Disposition::Retry(Duration::from_secs(300)));
    }
}
