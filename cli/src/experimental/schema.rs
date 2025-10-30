use anyhow::{Context, Result};
use inquire::{Select, Text};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use tracing::info;

use crate::invocation_context::context;

#[derive(Debug, Serialize, Deserialize)]
struct SchemaConfig {
    schema_version: i64,
    updated_at: String,
    event_count: usize,
    output_paths: HashMap<String, String>,
}

pub fn pull(_host: Option<String>, output_override: Option<String>) -> Result<()> {
    // Select language
    let language = select_language()?;

    info!("Fetching {} definitions from PostHog...", language_display_name(&language));

    // Load credentials
    let token = context().token.clone();
    let host = token.get_host();

    // Determine output path
    let output_path = determine_output_path(&language, output_override)?;

    // Fetch TypeScript definitions from the server
    let ts_content = fetch_typescript_definitions(&host, &token.env_id, &token.token)?;

    // Count the number of events in the TypeScript file
    let event_count = ts_content.lines().filter(|line| line.trim().starts_with("'") && line.contains(":")).count();

    info!("✓ Fetched {} definitions for {} events", language_display_name(&language), event_count);

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
    let schema_config = create_schema_config(event_count, &language, output_path.clone())?;
    let schema_json = serde_json::to_string_pretty(&schema_config)
        .context("Failed to serialize schema config")?;
    fs::write("posthog.json", schema_json)
        .context("Failed to write posthog.json")?;
    info!("✓ Updated posthog.json");

    println!("\n✓ Schema sync complete!");
    println!("\nNext steps:");
    println!("  1. Import PostHog from your generated module:");
    println!("     import posthog from './{}'", output_path);
    println!("  2. Use typed events with autocomplete and type safety:");
    println!("     posthog.captureTyped('event_name', {{ property: 'value' }})");
    println!("  3. Or use regular capture() for flexibility:");
    println!("     posthog.capture('dynamic_event', {{ any: 'data' }})");
    println!();

    Ok(())
}

fn determine_output_path(language: &str, output_override: Option<String>) -> Result<String> {
    // If CLI override is provided, use it (and normalize it)
    if let Some(path) = output_override {
        return Ok(normalize_output_path(&path, language));
    }

    // Check if posthog.json exists and has an output_path for this language
    if Path::new("posthog.json").exists() {
        match fs::read_to_string("posthog.json") {
            Ok(content) => {
                if let Ok(config) = serde_json::from_str::<SchemaConfig>(&content) {
                    if let Some(path) = config.output_paths.get(language) {
                        return Ok(path.clone());
                    }
                }
            }
            Err(_) => {}
        }
    }

    // Get current directory for help message
    let current_dir = std::env::current_dir()
        .ok()
        .and_then(|p| p.to_str().map(|s| s.to_string()))
        .unwrap_or_else(|| ".".to_string());

    // Prompt user for output path
    let default_filename = default_output_path(language);
    let help_message = format!("Your app will import PostHog from this file, so it should be accessible throughout your codebase (e.g., src/lib/, app/lib/, or your project root). Current directory: {}", current_dir);

    let path = Text::new(&format!("Where should we save the {} typed PostHog module?", language_display_name(language)))
        .with_default(&default_filename)
        .with_help_message(&help_message)
        .prompt()
        .unwrap_or(default_filename.clone());

    // Normalize the path (handle directories)
    Ok(normalize_output_path(&path, language))
}

fn normalize_output_path(path: &str, language: &str) -> String {
    let path_obj = Path::new(path);

    // If the path exists and is a directory, append the default filename
    if path_obj.exists() && path_obj.is_dir() {
        let default_filename = default_output_path(language);
        return path_obj.join(default_filename)
            .to_string_lossy()
            .to_string();
    }

    // If the path doesn't exist but looks like a directory (ends with /), append default filename
    if path.ends_with('/') || path.ends_with('\\') {
        let default_filename = default_output_path(language);
        return Path::new(path).join(default_filename)
            .to_string_lossy()
            .to_string();
    }

    // Otherwise, assume it's a file path and use it as-is
    path.to_string()
}

pub fn status() -> Result<()> {
    // Check authentication
    println!("\nPostHog Schema Sync Status\n");

    println!("Authentication:");
    let token = context().token.clone();
    println!("  ✓ Authenticated");
    println!("  Host: {}", token.get_host());
    println!("  Project ID: {}", token.env_id);
    let masked_token = format!("{}****{}",
                               &token.token[..4],
                               &token.token[token.token.len()-4..]
    );
    println!("  Token: {}", masked_token);

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

                        println!("\n  Type definitions:");
                        for (language, path) in &config.output_paths {
                            if Path::new(path).exists() {
                                println!("    ✓ {}: {}", language_display_name(language), path);
                            } else {
                                println!("    ! {}: {} (missing)", language_display_name(language), path);
                            }
                        }

                        if config.output_paths.is_empty() {
                            println!("    ! No type definitions configured");
                            println!("    Run: posthog-cli schema pull");
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

    let client = &context().client;
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

fn create_schema_config(event_count: usize, language: &str, output_path: String) -> Result<SchemaConfig> {
    use chrono::Utc;

    // Load existing config to preserve other languages
    let mut output_paths = if Path::new("posthog.json").exists() {
        match fs::read_to_string("posthog.json") {
            Ok(content) => {
                if let Ok(config) = serde_json::from_str::<SchemaConfig>(&content) {
                    config.output_paths
                } else {
                    HashMap::new()
                }
            }
            Err(_) => HashMap::new(),
        }
    } else {
        HashMap::new()
    };

    // Update the path for the current language
    output_paths.insert(language.to_string(), output_path);

    Ok(SchemaConfig {
        schema_version: Utc::now().timestamp_millis(),
        updated_at: Utc::now().to_rfc3339(),
        event_count,
        output_paths,
    })
}

fn select_language() -> Result<String> {
    let languages = vec!["typescript"];

    if languages.len() == 1 {
        return Ok(languages[0].to_string());
    }

    let language = Select::new("Which language would you like to download?", languages)
        .prompt()
        .context("Failed to select language")?;

    Ok(language.to_string())
}

fn language_display_name(language: &str) -> &str {
    match language {
        "typescript" => "TypeScript",
        "ts" => "TypeScript",
        _ => language,
    }
}

fn default_output_path(language: &str) -> String {
    match language {
        "typescript" | "ts" => "posthog-typed.ts".to_string(),
        _ => format!("posthog-typed.{}", language),
    }
}
