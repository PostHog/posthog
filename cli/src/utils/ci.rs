use std::sync::atomic::{AtomicBool, Ordering};

// Providers that set no `CI` variable, or set one a job can override, still set one of these.
const CI_PROVIDER_VARS: [&str; 26] = [
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "CIRCLECI",
    "BUILDKITE",
    "JENKINS_URL",
    "TRAVIS",
    "BITBUCKET_COMMIT",
    "TF_BUILD",
    "CODEBUILD_BUILD_ARN",
    "TEAMCITY_VERSION",
    "DRONE",
    "SEMAPHORE",
    "APPVEYOR",
    "BITRISE_IO",
    "CM_BUILD_ID",
    "EAS_BUILD",
    "HARNESS_BUILD_ID",
    "DEPOT_JOB_URL",
    "NETLIFY",
    "CF_PAGES",
    "WORKERS_CI",
    "RENDER",
    "RAILWAY_SERVICE_ID",
    "HEROKU_TEST_RUN_ID",
    "CI_XCODE_CLOUD",
    "BUILDER_OUTPUT",
];

// CI logs are often readable by more people than the person who ran the command, and PostHog's error
// details and the debug payloads can repeat values from the request. They show only outside CI. The
// flag starts hidden, so code that runs before `init_detailed_diagnostics`, such as unit tests, hides them.
static DETAILED_DIAGNOSTICS: AtomicBool = AtomicBool::new(false);

pub fn is_ci(var: impl Fn(&str) -> Option<String>) -> bool {
    let ci_flag = var("CI").is_some_and(|value| {
        !matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "" | "0" | "false"
        )
    });

    ci_flag || CI_PROVIDER_VARS.iter().any(|name| var(name).is_some())
}

pub fn init_detailed_diagnostics() {
    let in_ci =
        is_ci(|name| std::env::var_os(name).map(|value| value.to_string_lossy().into_owned()));

    DETAILED_DIAGNOSTICS.store(!in_ci, Ordering::Relaxed);
}

pub fn detailed_diagnostics() -> bool {
    DETAILED_DIAGNOSTICS.load(Ordering::Relaxed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_ci_from_the_ci_flag_or_a_provider_variable() {
        for (env, expected) in [
            (vec![], false),
            (vec![("CI", "true")], true),
            (vec![("CI", "1")], true),
            (vec![("CI", "")], false),
            (vec![("CI", "0")], false),
            (vec![("CI", "False")], false),
            (vec![("JENKINS_URL", "https://jenkins.example.com")], true),
            (vec![("CI", "false"), ("TF_BUILD", "True")], true),
            (vec![("WORKERS_CI", "1")], true),
            (vec![("CI", "false"), ("WORKERS_CI", "1")], true),
            (vec![("RENDER", "true")], true),
            (vec![("RAILWAY_SERVICE_ID", "synthetic-service")], true),
            (vec![("HEROKU_TEST_RUN_ID", "synthetic-run")], true),
            (vec![("CI_XCODE_CLOUD", "TRUE")], true),
            (vec![("HOME", "/home/user")], false),
        ] {
            let lookup = |name: &str| {
                env.iter()
                    .find(|(key, _)| *key == name)
                    .map(|(_, value)| value.to_string())
            };

            assert_eq!(is_ci(lookup), expected, "{env:?}");
        }
    }
}
