use anyhow::{bail, Result};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct BackfillStatus {
    enabled: bool,
}

pub fn project_backfill_enabled() -> Option<bool> {
    let client = &crate::invocation_context::context().client;
    let response = client
        .send_get(client.project_url("logs/backfill_status").ok()?, |req| req)
        .ok()?;
    let status: BackfillStatus = response.json().ok()?;
    Some(status.enabled)
}

/// Intake drops every record from a project that may not backfill and still answers 200, so the
/// run stops here instead. An unreadable answer only warns, because intake enforces it either way.
pub fn check_backfill_allowed(enabled: Option<bool>) -> Result<Option<&'static str>> {
    match enabled {
        Some(true) => Ok(None),
        Some(false) => bail!(
            "This project can't import historical logs yet, so PostHog would drop everything this \
             import sends. Nothing was sent. Contact PostHog support to turn on historical imports \
             for this project."
        ),
        None => Ok(Some(
            "Couldn't check whether this project can import historical logs. If it can't, PostHog \
             drops what this import sends. Give the API key the logs:read scope to check before \
             sending.",
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_a_refusal_stops_the_run() {
        for (case, enabled, stops, warns) in [
            ("allowed", Some(true), false, false),
            ("refused", Some(false), true, false),
            ("unreadable", None, false, true),
        ] {
            let result = check_backfill_allowed(enabled);
            assert_eq!(result.is_err(), stops, "{case}");
            assert_eq!(matches!(result, Ok(Some(_))), warns, "{case}");
        }
    }
}
