use chrono::{DateTime, TimeDelta, Utc};
use serde::Deserialize;

use super::plan::{day, whole_days};

/// Kept in sync with `DEFAULT_LOGS_RETENTION_DAYS` in `posthog/models/team/logs_retention.py`,
/// which applies when a project never set its logs retention.
const DEFAULT_RETENTION_DAYS: i64 = 14;

#[derive(Debug, Deserialize)]
struct Team {
    #[serde(default)]
    logs_settings: Option<LogsSettings>,
}

#[derive(Debug, Deserialize)]
struct LogsSettings {
    #[serde(default)]
    retention_days: Option<i64>,
}

/// The project's default logs retention in days, or `None` when the project cannot be read, for
/// example because the API key lacks `project:read`.
pub fn project_retention_days() -> Option<i64> {
    let client = &crate::invocation_context::context().client;
    let response = client.send_get(client.env_url("").ok()?, |req| req).ok()?;
    let team: Team = response.json().ok()?;
    Some(retention_days(team))
}

fn retention_days(team: Team) -> i64 {
    team.logs_settings
        .and_then(|settings| settings.retention_days)
        .filter(|days| *days > 0)
        .unwrap_or(DEFAULT_RETENTION_DAYS)
}

pub fn retention_cutoff(retention_days: i64, now: DateTime<Utc>) -> DateTime<Utc> {
    now - TimeDelta::days(retention_days)
}

#[derive(Debug, PartialEq)]
pub enum Expiry {
    Unknown,
    WithinRetention,
    PartlyExpired {
        retention_days: i64,
        cutoff: DateTime<Utc>,
        expired_days: i64,
        total_days: i64,
    },
}

pub fn assess(
    from: DateTime<Utc>,
    to: DateTime<Utc>,
    retention_days: Option<i64>,
    now: DateTime<Utc>,
) -> Expiry {
    let Some(retention_days) = retention_days else {
        return Expiry::Unknown;
    };
    let cutoff = retention_cutoff(retention_days, now);
    if from >= cutoff {
        return Expiry::WithinRetention;
    }
    // Dropped days are the total less the days the dry run reports as sent, so the two add up.
    let total_days = whole_days(from, to);
    Expiry::PartlyExpired {
        retention_days,
        cutoff,
        expired_days: total_days - whole_days(cutoff.min(to), to),
        total_days,
    }
}

pub struct Confirmation {
    pub summary: String,
    pub prompt: String,
}

impl Expiry {
    pub fn confirmation(&self) -> Option<Confirmation> {
        match self {
            Expiry::WithinRetention => None,
            Expiry::Unknown => Some(Confirmation {
                summary: "Could not read this project's logs retention, so this run cannot tell \
                          which records PostHog keeps. Records older than the retention are \
                          dropped when they arrive."
                    .to_string(),
                prompt: "Import without a retention check?".to_string(),
            }),
            Expiry::PartlyExpired {
                retention_days,
                cutoff,
                expired_days,
                total_days,
            } => Some(Confirmation {
                summary: format!(
                    "This project keeps logs for {retention_days} days. Records before {} are \
                     dropped when they arrive: {expired_days} of the {total_days} days in this \
                     range. Raise logs retention in the project settings to keep them.",
                    day(*cutoff)
                ),
                prompt: format!("Skip records before {} and import the rest?", day(*cutoff)),
            }),
        }
    }

    pub fn effective_from(&self, from: DateTime<Utc>, to: DateTime<Utc>) -> DateTime<Utc> {
        match self {
            Expiry::PartlyExpired { cutoff, .. } => (*cutoff).min(to),
            Expiry::Unknown | Expiry::WithinRetention => from,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_unset_or_empty_retention_falls_back_to_the_project_default() {
        for json in [
            r#"{}"#,
            r#"{"logs_settings": null}"#,
            r#"{"logs_settings": {"retention_days": null}}"#,
        ] {
            let team: Team = serde_json::from_str(json).unwrap();
            assert_eq!(retention_days(team), DEFAULT_RETENTION_DAYS, "{json}");
        }
        let team: Team =
            serde_json::from_str(r#"{"logs_settings": {"retention_days": 540}}"#).unwrap();
        assert_eq!(retention_days(team), 540);
    }

    #[test]
    fn a_range_reaching_past_retention_reports_how_much_is_dropped() {
        let now = DateTime::parse_from_rfc3339("2026-10-05T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let from = now - TimeDelta::days(100);

        assert_eq!(
            assess(from, now, Some(30), now),
            Expiry::PartlyExpired {
                retention_days: 30,
                cutoff: now - TimeDelta::days(30),
                expired_days: 70,
                total_days: 100,
            }
        );
        assert_eq!(assess(from, now, Some(365), now), Expiry::WithinRetention);
        assert_eq!(assess(from, now, None, now), Expiry::Unknown);

        // The run sends from the cutoff, and from nothing at all when the whole range is past it.
        let partly = assess(from, now, Some(30), now);
        assert_eq!(partly.effective_from(from, now), now - TimeDelta::days(30));
        let whole = assess(from, from + TimeDelta::days(10), Some(30), now);
        assert_eq!(
            whole.effective_from(from, from + TimeDelta::days(10)),
            from + TimeDelta::days(10)
        );
        assert_eq!(assess(from, now, None, now).effective_from(from, now), from);
    }
}
