use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

use crate::utils::auth::load_token;
use crate::utils::client::get_client;
use crate::utils::posthog::capture_command_invoked;

#[derive(Debug, Serialize, Deserialize)]
struct UserResponse {
    id: i64,
    uuid: String,
    email: String,
    first_name: Option<String>,
    last_name: Option<String>,
    team: Option<TeamInfo>,
    organization: Option<OrganizationInfo>,
}

#[derive(Debug, Serialize, Deserialize)]
struct TeamInfo {
    id: i64,
    uuid: String,
    name: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct OrganizationInfo {
    id: String,
    name: String,
}

pub fn status() -> Result<()> {
    let token = match load_token() {
        Ok(token) => token,
        Err(_) => {
            println!("❌ Not authenticated");
            println!("Run 'posthog login' to authenticate with PostHog");
            return Ok(());
        }
    };

    let host = token.get_host(None);
    let client = get_client()?;

    let _ = capture_command_invoked("status", Some(&token.env_id));

    let url = format!("{}/api/users/@me/", host);

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token.token))
        .send()
        .context("Failed to send request")?;

    if !response.status().is_success() {
        if response.status() == 401 {
            anyhow::bail!("Authentication failed. Your token may be invalid or expired. Try running 'posthog login' again.");
        }
        anyhow::bail!("Failed to get status: {}", response.status());
    }

    let user_data: UserResponse = response.json().context("Failed to parse status response")?;

    println!("\n✅ Logged in to PostHog");
    println!("──────────────────────");
    println!("Host:         {}", host);
    println!("Environment:  {}", token.env_id);
    println!("");

    let first_name = user_data.first_name.as_deref().unwrap_or("");
    let last_name = user_data.last_name.as_deref().unwrap_or("");
    let full_name = format!("{} {}", first_name, last_name).trim().to_string();

    if !full_name.is_empty() {
        println!("User:         {} ({})", full_name, user_data.email);
    } else {
        println!("User:         {}", user_data.email);
    }

    if let Some(org) = user_data.organization {
        println!("Organization: {} (ID: {})", org.name, org.id);
    }

    if let Some(team) = user_data.team {
        println!("Team:         {} (ID: {})", team.name, team.id);
    }

    Ok(())
}
