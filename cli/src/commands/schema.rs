use anyhow::{Context, Result};
use inquire::Text;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use tracing::info;

use crate::utils::{auth::load_token, client::get_client};

#[derive(Debug, Serialize, Deserialize)]
struct SchemaConfig {
    schema_version: i64,
    updated_at: String,
    event_count: usize,
    output_path: String,
}

pub fn pull(host: Option<String>, output_override: Option<String>) -> Result<()> {
    info!("Fetching TypeScript definitions from PostHog...");

    // Load credentials
    let token = load_token()?;
    let host = token.get_host(host.as_deref());

    // Determine output path
    let output_path = determine_output_path(output_override)?;

    // Fetch TypeScript definitions from the server
    let ts_content = fetch_typescript_definitions(&host, &token.env_id, &token.token)?;

    // Count the number of events in the TypeScript file
    let event_count = ts_content.lines().filter(|line| line.trim().starts_with("'") && line.contains(":")).count() / 2; // Divide by 2 since it appears in both modules

    info!("✓ Fetched TypeScript definitions for {} events", event_count);

    // Write TypeScript definitions to file
    info!("Writing {}...", output_path);

    // Create parent directories if they don't exist
    if let Some(parent) = Path::new(&output_path).parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .context(format!("Failed to create directory {}", parent.display()))?;
        }
    }

    fs::write(&output_path, &ts_content)
        .context(format!("Failed to write {}", output_path))?;
    info!("✓ Generated {}", output_path);

    // Update schema configuration
    info!("Updating posthog.json...");
    let schema_config = create_schema_config(event_count, output_path.clone())?;
    let schema_json = serde_json::to_string_pretty(&schema_config)
        .context("Failed to serialize schema config")?;
    fs::write("posthog.json", schema_json)
        .context("Failed to write posthog.json")?;
    info!("✓ Updated posthog.json");

    println!("\n✓ Schema sync complete!");
    println!("\nNext steps:");
    println!("  1. Import the types in your code:");
    println!("     import type {{}} from \"./posthog-events\"");
    println!("  2. Use typed events with PostHog:");
    println!("     posthog.capture(\"signed_up\", {{ email: \"...\" }})");
    println!();

    Ok(())
}

fn determine_output_path(output_override: Option<String>) -> Result<String> {
    // If CLI override is provided, use it
    if let Some(path) = output_override {
        return Ok(path);
    }

    // Check if posthog.json exists and has an output_path
    if Path::new("posthog.json").exists() {
        match fs::read_to_string("posthog.json") {
            Ok(content) => {
                if let Ok(config) = serde_json::from_str::<SchemaConfig>(&content) {
                    return Ok(config.output_path);
                }
            }
            Err(_) => {}
        }
    }

    // Prompt user for output path
    let default_path = "posthog-events.d.ts".to_string();
    let path = Text::new("Where should we save the TypeScript definitions?")
        .with_default(&default_path)
        .with_help_message("This will be saved in posthog.json for future runs")
        .prompt()
        .unwrap_or(default_path.clone());

    Ok(path)
}

pub fn status() -> Result<()> {
    // Check authentication
    println!("\nPostHog Schema Sync Status\n");

    println!("Authentication:");
    match load_token() {
        Ok(token) => {
            println!("  ✓ Authenticated");
            println!("  Host: {}", token.get_host(None));
            println!("  Project ID: {}", token.env_id);
            let masked_token = format!("{}****{}",
                &token.token[..4],
                &token.token[token.token.len()-4..]
            );
            println!("  Token: {}", masked_token);
        }
        Err(_) => {
            println!("  ✗ Not authenticated");
            println!("  Run: posthog-cli login");
        }
    }

    println!();

    // Check schema status
    println!("Schema:");
    if Path::new("posthog.json").exists() {
        match fs::read_to_string("posthog.json") {
            Ok(content) => {
                match serde_json::from_str::<SchemaConfig>(&content) {
                    Ok(config) => {
                        println!("  ✓ Schema synced");
                        println!("  Version: {}", config.schema_version);
                        println!("  Updated: {}", config.updated_at);
                        println!("  Events: {}", config.event_count);
                        println!("  Output: {}", config.output_path);

                        if Path::new(&config.output_path).exists() {
                            println!("  ✓ Type definitions: {}", config.output_path);
                        } else {
                            println!("  ! Type definitions missing");
                            println!("  Run: posthog-cli schema pull");
                        }
                    }
                    Err(_) => {
                        println!("  ! Invalid posthog.json format");
                    }
                }
            }
            Err(_) => {
                println!("  ✗ Schema not synced");
                println!("  Run: posthog-cli schema pull");
            }
        }
    } else {
        println!("  ✗ Schema not synced");
        println!("  Run: posthog-cli schema pull");
    }

    println!();

    Ok(())
}

fn fetch_typescript_definitions(host: &str, env_id: &str, token: &str) -> Result<String> {
    let url = format!("{}/api/projects/{}/event_definitions/typescript/", host, env_id);

    let client = get_client()?;
    let response = client
        .get(&url)
        .bearer_auth(token)
        .send()
        .context("Failed to fetch TypeScript definitions")?;

    if !response.status().is_success() {
        return Err(anyhow::anyhow!(
            "Failed to fetch TypeScript definitions: HTTP {}",
            response.status()
        ));
    }

    let ts_content = response
        .text()
        .context("Failed to read TypeScript definitions response")?;

    Ok(ts_content)
}

fn create_schema_config(event_count: usize, output_path: String) -> Result<SchemaConfig> {
    use chrono::Utc;

    Ok(SchemaConfig {
        schema_version: Utc::now().timestamp_millis(),
        updated_at: Utc::now().to_rfc3339(),
        event_count,
        output_path,
    })
}
