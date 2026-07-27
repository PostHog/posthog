use anyhow::{bail, Context, Error, Result};
use inquire::{Select, Text};
use serde::{Deserialize, Serialize};
use std::io::IsTerminal;
use std::time::Duration;
use std::{io, thread};
use tracing::info;

use crate::{
    invocation_context::{context, init_context},
    utils::auth::{
        env_id_validator, host_validator, token_validator, CredentialProvider, HomeDirProvider,
        Token,
    },
};

#[derive(Debug, Deserialize)]
struct DeviceCodeResponse {
    device_code: String,
    user_code: String,
    verification_uri_complete: String,
    expires_in: u64,
    interval: u64,
}

#[derive(Debug, Serialize)]
struct PollRequest {
    device_code: String,
}

#[derive(Debug, Deserialize)]
struct PollResponse {
    status: String,
    personal_api_key: Option<String>,
    project_id: Option<String>,
    scopes: Option<Vec<String>>,
}

// The `agent-cli` use case grants the full MCP / `posthog-cli api` scope set
// (a superset of schema + error_tracking + endpoints), so a freshly logged-in
// CLI can run the agent interface without re-authorizing.
const DEFAULT_LOGIN_USE_CASES: &[&str] = &["agent-cli"];
const NEXT_COMMAND_AGENT_CLI: &str = "posthog-cli api tools";
const NEXT_COMMAND_ERROR_TRACKING: &str = "posthog-cli sourcemap --help";
const NEXT_COMMAND_SCHEMA: &str = "posthog-cli exp schema pull";
const NEXT_COMMAND_ENDPOINTS: &str = "posthog-cli exp endpoints list";
const NEXT_COMMAND_DEFAULT: &str = "posthog-cli --help";

pub fn login(host_override: Option<String>) -> Result<()> {
    if !io::stdout().is_terminal() {
        bail!("Failed to login. If you are running on a CI, skip this step and use POSTHOG_CLI_HOST, POSTHOG_CLI_PROJECT_ID, POSTHOG_CLI_API_KEY env variables when running commands")
    }
    login_with_use_cases(host_override, DEFAULT_LOGIN_USE_CASES.to_vec())
}

pub fn login_with_use_cases(host_override: Option<String>, use_cases: Vec<&str>) -> Result<()> {
    let host = if let Some(override_host) = host_override {
        // Strip trailing slashes to avoid double slashes in URLs
        override_host.trim_end_matches('/').to_string()
    } else {
        // Prompt user to select region or manual login
        let options = vec!["US", "EU", "Manual"];
        let selection = Select::new("Select your PostHog region:", options)
            .with_help_message("Choose the region where your PostHog data is hosted, or 'Manual' to enter your own details")
            .prompt()?;

        match selection {
            "US" => "https://us.posthog.com".to_string(),
            "EU" => "https://eu.posthog.com".to_string(),
            "Manual" => {
                return manual_login();
            }
            _ => unreachable!(),
        }
    };

    info!("🔐 Starting OAuth Device Flow authentication...");
    info!("Connecting to: {}", host);

    // Step 1: Request device code
    let device_data = request_device_code(&host)?;

    // Add use_cases parameter to the verification URL
    let use_cases_param = use_cases.join(",");
    let verification_url = if device_data.verification_uri_complete.contains('?') {
        format!(
            "{}&use_cases={}",
            device_data.verification_uri_complete, use_cases_param
        )
    } else {
        format!(
            "{}?use_cases={}",
            device_data.verification_uri_complete, use_cases_param
        )
    };

    println!();
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!("  📱 Authorization Required");
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!();
    println!("To authenticate, visit this URL in your browser:");
    println!("  {verification_url}");
    println!();
    println!("Your authorization code:");
    println!("  ✨ {} ✨", device_data.user_code);
    println!();
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!();

    // Step 2: Try to open browser
    if let Err(e) = open_browser(&verification_url) {
        info!("Could not open browser automatically: {}", e);
        info!("Please open the URL manually");
    } else {
        info!("✓ Opened browser for authorization");
    }

    // Step 3: Poll for authorization
    info!("Waiting for authorization...");
    let poll_response = poll_for_authorization(
        &host,
        &device_data.device_code,
        device_data.interval,
        device_data.expires_in,
    )?;
    let authorized_scopes = poll_response.scopes.clone().unwrap_or_default();

    info!("✓ Successfully authenticated!");

    // Step 4: Save credentials
    let token = Token {
        host: Some(host),
        token: poll_response.personal_api_key.unwrap(),
        env_id: poll_response.project_id.unwrap(),
    };
    let provider = HomeDirProvider;
    provider.store_credentials(token)?;

    info!("Token saved to: {}", provider.report_location());

    complete_login(
        &provider,
        "interactive_login",
        &authorized_scopes,
        &use_cases,
    )
}

fn request_device_code(host: &str) -> Result<DeviceCodeResponse, Error> {
    let client = reqwest::blocking::Client::new();
    let url = format!("{host}/api/cli-auth/device-code/");

    let response = client
        .post(&url)
        .header("Content-Type", "application/json")
        .send()
        .context("Failed to request device code")?;

    if !response.status().is_success() {
        return Err(anyhow::anyhow!(
            "Failed to request device code: HTTP {}",
            response.status()
        ));
    }

    let device_data: DeviceCodeResponse = response
        .json()
        .context("Failed to parse device code response")?;

    Ok(device_data)
}

fn open_browser(url: &str) -> Result<(), Error> {
    // Try to open browser using platform-specific commands
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(url)
            .spawn()
            .context("Failed to open browser")?;
    }

    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(url)
            .spawn()
            .context("Failed to open browser")?;
    }

    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(&["/C", "start", url])
            .spawn()
            .context("Failed to open browser")?;
    }

    Ok(())
}

fn poll_for_authorization(
    host: &str,
    device_code: &str,
    interval_seconds: u64,
    expires_in_seconds: u64,
) -> Result<PollResponse, Error> {
    let client = reqwest::blocking::Client::new();
    let url = format!("{host}/api/cli-auth/poll/");
    let max_attempts = (expires_in_seconds / interval_seconds) + 1;
    let poll_interval = Duration::from_secs(interval_seconds);

    for attempt in 1..=max_attempts {
        thread::sleep(poll_interval);

        let request = PollRequest {
            device_code: device_code.to_string(),
        };

        let response = client
            .post(&url)
            .header("Content-Type", "application/json")
            .json(&request)
            .send()
            .context("Failed to poll for authorization")?;

        let status_code = response.status();

        if status_code.as_u16() == 202 {
            // Still pending
            if attempt % 3 == 0 {
                info!(
                    "Still waiting for authorization... (attempt {}/{})",
                    attempt, max_attempts
                );
            }
            continue;
        }

        // Parse response body for both success and error cases
        let poll_response: PollResponse =
            response.json().context("Failed to parse poll response")?;

        if status_code.is_success() && poll_response.status == "authorized" {
            return Ok(poll_response);
        }

        if status_code.as_u16() == 400 && poll_response.status == "expired" {
            return Err(anyhow::anyhow!(
                "Authorization code expired. Please try again."
            ));
        }

        return Err(anyhow::anyhow!(
            "Unexpected response during polling: HTTP {} - status: {}",
            status_code,
            poll_response.status
        ));
    }

    Err(anyhow::anyhow!(
        "Authorization timed out. Please try again."
    ))
}

fn has_scope_action(scopes: &[String], object: &str) -> bool {
    scopes.iter().any(|scope| {
        scope == "*" || scope == &format!("{object}:read") || scope == &format!("{object}:write")
    })
}

fn use_cases_include(use_cases: &[&str], candidates: &[&str]) -> bool {
    use_cases
        .iter()
        .any(|use_case| candidates.contains(use_case))
}

fn recommended_next_command(scopes: &[String], use_cases: &[&str]) -> &'static str {
    if !scopes.is_empty() {
        if has_scope_action(scopes, "user")
            && has_scope_action(scopes, "project")
            && has_scope_action(scopes, "query")
        {
            return NEXT_COMMAND_AGENT_CLI;
        }

        if has_scope_action(scopes, "error_tracking") {
            return NEXT_COMMAND_ERROR_TRACKING;
        }

        if has_scope_action(scopes, "event_definition")
            && has_scope_action(scopes, "property_definition")
        {
            return NEXT_COMMAND_SCHEMA;
        }

        if has_scope_action(scopes, "endpoint") {
            return NEXT_COMMAND_ENDPOINTS;
        }

        return NEXT_COMMAND_DEFAULT;
    }

    if use_cases_include(use_cases, &["agent-cli", "agent"]) {
        return NEXT_COMMAND_AGENT_CLI;
    }

    if use_cases_include(use_cases, &["error_tracking", "error-tracking"]) {
        return NEXT_COMMAND_ERROR_TRACKING;
    }

    if use_cases_include(use_cases, &["schema"]) {
        return NEXT_COMMAND_SCHEMA;
    }

    if use_cases_include(use_cases, &["endpoints"]) {
        return NEXT_COMMAND_ENDPOINTS;
    }

    NEXT_COMMAND_DEFAULT
}

fn complete_login(
    provider: &HomeDirProvider,
    command_name: &str,
    scopes: &[String],
    use_cases: &[&str],
) -> Result<(), Error> {
    // Login is the only command that doesn't have a context coming in - because it modifies the context
    init_context(None, false, None, None)?;
    context().capture_command_invoked(command_name);
    let next_command = recommended_next_command(scopes, use_cases);

    println!();
    println!("🎉 Authentication complete!");
    println!("Credentials saved to: {}", provider.report_location());
    println!();
    println!("You can now use the CLI:");
    println!("  {next_command}");
    println!();

    Ok(())
}

fn manual_login() -> Result<(), Error> {
    info!("🔐 Manual login...");

    let host = Text::new("Enter the PostHog host URL")
        .with_default("https://us.posthog.com")
        .with_validator(host_validator)
        .prompt()?;

    let env_id = Text::new("Enter your project ID (the number in your PostHog homepage URL)")
        .with_validator(env_id_validator)
        .prompt()?;

    let token = Text::new("Enter your personal API token")
        .with_validator(token_validator)
        .with_help_message("See posthog.com/docs/api#private-endpoint-authentication. It will need to have the 'error tracking write' scope. To enable tooling, select the 'Agent CLI' preset.")
        .prompt()?;

    let token = Token {
        host: Some(host.trim_end_matches('/').to_string()),
        token,
        env_id,
    };
    let provider = HomeDirProvider;
    provider.store_credentials(token)?;

    info!("Token saved to: {}", provider.report_location());

    complete_login(&provider, "manual_login", &[], &[])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_login_requests_the_agent_cli_use_case() {
        // The agent-cli use case is what grants the CLI the full `posthog-cli api`
        // scope set; narrowing it here would silently break agent commands.
        assert_eq!(DEFAULT_LOGIN_USE_CASES, &["agent-cli"]);
    }

    #[test]
    fn recommends_api_tools_for_agent_cli_use_case() {
        assert_eq!(
            recommended_next_command(&[], &["agent-cli"]),
            NEXT_COMMAND_AGENT_CLI
        );
    }

    #[test]
    fn recommends_api_tools_for_agent_capable_scopes() {
        let scopes = vec![
            "user:read".to_string(),
            "project:read".to_string(),
            "query:read".to_string(),
        ];

        assert_eq!(
            recommended_next_command(&scopes, &["error_tracking"]),
            NEXT_COMMAND_AGENT_CLI
        );
    }

    #[test]
    fn recommends_sourcemap_for_error_tracking_scopes() {
        let scopes = vec!["error_tracking:write".to_string()];

        assert_eq!(
            recommended_next_command(&scopes, &["agent-cli"]),
            NEXT_COMMAND_ERROR_TRACKING
        );
    }

    #[test]
    fn recommends_schema_for_schema_scopes() {
        let scopes = vec![
            "event_definition:read".to_string(),
            "property_definition:read".to_string(),
        ];

        assert_eq!(recommended_next_command(&scopes, &[]), NEXT_COMMAND_SCHEMA);
    }
}
