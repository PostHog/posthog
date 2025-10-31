use anyhow::{Context, Result};
use inquire::{Select, Text};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use tracing::info;

use crate::invocation_context::context;

#[derive(Debug, Serialize, Deserialize, Default)]
struct SchemaConfig {
    languages: HashMap<String, LanguageConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct LanguageConfig {
    output_path: String,
    schema_hash: String,
    updated_at: String,
    event_count: usize,
}

impl SchemaConfig {
    /// Load config from posthog.json, returns empty config if file doesn't exist or is invalid
    fn load() -> Self {
        let content = fs::read_to_string("posthog.json").ok();
        content
            .and_then(|c| serde_json::from_str(&c).ok())
            .unwrap_or_default()
    }

    /// Save config to posthog.json
    fn save(&self) -> Result<()> {
        let json = serde_json::to_string_pretty(self)
            .context("Failed to serialize schema config")?;
        fs::write("posthog.json", json)
            .context("Failed to write posthog.json")?;
        Ok(())
    }

    /// Get language config for a specific language
    fn get_language(&self, language: &str) -> Option<&LanguageConfig> {
        self.languages.get(language)
    }

    /// Get output path for a language
    fn get_output_path(&self, language: &str) -> Option<String> {
        self.languages.get(language).map(|l| l.output_path.clone())
    }

    /// Update language config, preserving other languages
    fn update_language(&mut self, language: &str, output_path: String, schema_hash: String, event_count: usize) {
        use chrono::Utc;

        self.languages.insert(
            language.to_string(),
            LanguageConfig {
                output_path,
                schema_hash,
                updated_at: Utc::now().to_rfc3339(),
                event_count,
            },
        );
    }
}

#[derive(Debug, Deserialize)]
struct TypescriptResponse {
    content: String,
    event_count: usize,
    schema_hash: String,
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
    let response = fetch_typescript_definitions(&host, &token.env_id, &token.token)?;

    info!("✓ Fetched {} definitions for {} events", language_display_name(&language), response.event_count);

    // Check if schema has changed for this language
    let config = SchemaConfig::load();
    if let Some(lang_config) = config.get_language(&language) {
        if lang_config.schema_hash == response.schema_hash {
            info!("Schema unchanged for {} (hash: {})", language, response.schema_hash);
            println!("\n✓ {} schema is already up to date!", language_display_name(&language));
            println!("  No changes detected - skipping file write.");
            return Ok(());
        }
    }

    // Write TypeScript definitions to file
    info!("Writing {}...", output_path);

    // Create parent directories if they don't exist
    if let Some(parent) = Path::new(&output_path).parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .context(format!("Failed to create directory {}", parent.display()))?;
        }
    }

    fs::write(&output_path, &response.content)
        .context(format!("Failed to write {}", output_path))?;
    info!("✓ Generated {}", output_path);

    // Update schema configuration for this language
    info!("Updating posthog.json...");
    let mut config = SchemaConfig::load();
    config.update_language(&language, output_path.clone(), response.schema_hash, response.event_count);
    config.save()?;
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
    let config = SchemaConfig::load();
    if let Some(path) = config.get_output_path(language) {
        return Ok(path);
    }

    // Get current directory for help message
    let current_dir = std::env::current_dir()
        .ok()
        .and_then(|p| p.to_str().map(|s| s.to_string()))
        .unwrap_or_else(|| ".".to_string());

    // Prompt user for output path
    let default_filename = default_output_path(language);
    let help_message = format!("Your app will import PostHog from this file, so it should be accessible throughout your codebase (e.g., src/lib/, app/lib/, or your project root). This path will be saved in posthog.json and can be changed later. Current directory: {}", current_dir);

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
    let config = SchemaConfig::load();

    if config.languages.is_empty() {
        println!("  ✗ No schemas synced");
        println!("  Run: posthog-cli exp schema pull");
    } else {
        println!("  ✓ Schemas synced\n");

        for (language, lang_config) in &config.languages {
            println!("  {}:", language_display_name(language));
            println!("    Hash: {}", lang_config.schema_hash);
            println!("    Updated: {}", lang_config.updated_at);
            println!("    Events: {}", lang_config.event_count);

            if Path::new(&lang_config.output_path).exists() {
                println!("    File: ✓ {}", lang_config.output_path);
            } else {
                println!("    File: ! {} (missing)", lang_config.output_path);
            }
            println!();
        }
    }

    println!();

    Ok(())
}

fn fetch_typescript_definitions(host: &str, env_id: &str, token: &str) -> Result<TypescriptResponse> {
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

    let json: TypescriptResponse = response
        .json()
        .context("Failed to parse TypeScript definitions response")?;

    Ok(json)
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
