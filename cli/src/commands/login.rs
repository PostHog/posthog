use anyhow::{Context, Error};
use inquire::Text;
use serde::{Deserialize, Serialize};
use std::thread;
use std::time::Duration;
use tracing::info;

use crate::utils::{
    auth::{host_validator, CredentialProvider, HomeDirProvider, Token},
    client::get_client,
    posthog::capture_command_invoked,
};

#[derive(Debug, Deserialize)]
struct DeviceCodeResponse {
    device_code: String,
    user_code: String,
    verification_uri: String,
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
    label: Option<String>,
    project_id: Option<String>,
}

pub fn login() -> Result<(), Error> {
    let host = Text::new("Enter the PostHog host URL")
        .with_default("https://us.posthog.com")
        .with_validator(host_validator)
        .prompt()?;

    // Given this is an interactive command, we're happy enough to not join the capture handle
    let _ = capture_command_invoked("interactive_login", None::<String>);

    info!("🔐 Starting OAuth Device Flow authentication...");

    // Step 1: Request device code
    let device_data = request_device_code(&host)?;

    println!();
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!("  📱 Authorization Required");
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!();
    println!("To authenticate, visit this URL in your browser:");
    println!("  {}", device_data.verification_uri);
    println!();
    println!("And enter this code:");
    println!("  ✨ {} ✨", device_data.user_code);
    println!();
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!();

    // Step 2: Try to open browser
    if let Err(e) = open_browser(&device_data.verification_uri_complete) {
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

    println!();
    println!("🎉 Authentication complete!");
    println!("Credentials saved to: {}", provider.report_location());
    println!();
    println!("You can now use the CLI:");
    println!("  posthog-cli schema pull");
    println!();

    Ok(())
}

fn request_device_code(host: &str) -> Result<DeviceCodeResponse, Error> {
    let client = get_client()?;
    let url = format!("{}/api/cli-auth/device-code/", host);

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
    let client = get_client()?;
    let url = format!("{}/api/cli-auth/poll/", host);
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
                info!("Still waiting for authorization... (attempt {}/{})", attempt, max_attempts);
            }
            continue;
        }

        // Parse response body for both success and error cases
        let poll_response: PollResponse = response
            .json()
            .context("Failed to parse poll response")?;

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
