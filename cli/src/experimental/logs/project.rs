use anyhow::{bail, Result};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct ProjectToken {
    api_token: String,
}

pub fn login_project_token() -> Option<String> {
    let client = &crate::invocation_context::context().client;
    let response = client.send_get(client.env_url("").ok()?, |req| req).ok()?;
    let project: ProjectToken = response.json().ok()?;
    Some(project.api_token)
}

/// The retention and backfill checks read the project from `posthog-cli login`, but the import writes
/// to the project that owns the write key. When they differ, both checks answer for the wrong project.
/// A missing value skips the comparison: the checks already warn when they cannot read the project,
/// and a real run fails later without a write key.
pub fn check_login_matches_target(
    login_token: Option<&str>,
    target_token: Option<&str>,
) -> Result<()> {
    match (login_token, target_token) {
        (Some(login), Some(target)) if login != target => bail!(
            "POSTHOG_PROJECT_API_KEY belongs to a different project than the one you're logged in to, \
             so the retention and historical import checks would describe the wrong project. Nothing \
             was sent. Run posthog-cli login and choose the project you're importing into."
        ),
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_two_different_projects_stop_the_run() {
        for (case, login, target, stops) in [
            ("same project", Some("phc_a"), Some("phc_a"), false),
            ("different projects", Some("phc_a"), Some("phc_b"), true),
            ("login project unreadable", None, Some("phc_b"), false),
            ("no write key in a dry run", Some("phc_a"), None, false),
        ] {
            assert_eq!(
                check_login_matches_target(login, target).is_err(),
                stops,
                "{case}"
            );
        }
    }
}
