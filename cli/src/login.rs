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
}

pub fn login(host_override: Option<String>) -> Result<()> {
    if !io::stdout().is_terminal() {
        bail!("Failed to login. If you are running on a CI, skip this step and use POSTHOG_CLI_HOST, POSTHOG_CLI_ENV_ID, POSTHOG_CLI_TOKEN env variables when running commands")
    }
    login_with_use_cases(host_override, vec!["schema", "error_tracking"])
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

    complete_login(&provider, "interactive_login")
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

fn complete_login(provider: &HomeDirProvider, command_name: &str) -> Result<(), Error> {
    // Login is the only command that doesn't have a context coming in - because it modifies the context
    init_context(None, false)?;
    context().capture_command_invoked(command_name);

    println!();
    println!("🎉 Authentication complete!");
    println!("Credentials saved to: {}", provider.report_location());
    println!();
    println!("You can now use the CLI:");
    println!("  posthog-cli schema pull");
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

    let token = Text::new(
        "Enter your personal API token",
    )
    .with_validator(token_validator)
    .with_help_message("See posthog.com/docs/api#private-endpoint-authentication. It will need to have the 'error tracking write' scope.")
    .prompt()?;

    let token = Token {
        host: Some(host.trim_end_matches('/').to_string()),
        token,
        env_id,
    };
    let provider = HomeDirProvider;
    provider.store_credentials(token)?;

    info!("Token saved to: {}", provider.report_location());

    complete_login(&provider, "manual_login")
}
