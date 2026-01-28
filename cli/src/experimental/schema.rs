use anyhow::{Context, Result};
use inquire::{Select, Text};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use tracing::info;

use crate::api::client::PHClient;
use crate::invocation_context::context;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
enum Language {
    TypeScript,
    Golang,
    Python,
}

impl Language {
    /// Get the language identifier used in API URLs
    fn as_str(&self) -> &'static str {
        match self {
            Language::TypeScript => "typescript",
            Language::Golang => "golang",
            Language::Python => "python",
        }
    }

    /// Get the display name for the language
    fn display_name(&self) -> &'static str {
        match self {
            Language::TypeScript => "TypeScript",
            Language::Golang => "Go",
            Language::Python => "Python",
        }
    }

    /// Get the default output filename for this language
    fn default_output_path(&self) -> &'static str {
        match self {
            Language::TypeScript => "posthog-typed.ts",
            Language::Golang => "posthog-typed.go",
            // Python uses underscore because hyphens aren't valid in Python module names
            Language::Python => "posthog_typed.py",
        }
    }

    /// Get the message to show to the user upon completion of the command (e.g. the next steps)
    fn next_steps_text(&self, output_path: &str) -> String {
        match self {
            Language::TypeScript => format!(
                r#"
1. Import PostHog from your generated module:
   import posthog from './{output_path}'
2. Use typed events with autocomplete and type safety on known events:
   posthog.capture('event_name', {{ property: 'value' }})
3. Use captureRaw() when you need to bypass type checking:
   posthog.captureRaw('dynamic_event_name', {{ whatever: 'data' }})
"#
            ),
            Language::Golang => format!(
                r#"
1. Install the PostHog Go SDK if you haven't already:
   go get github.com/posthog/posthog-go
2. Store the generated Go code in a folder named `typed` (e.g. `/src/lib/typed`):
   mkdir -p <your-directory>/src/lib/typed
   mv {output_path} <your-directory>/src/lib/typed
   > If you prefer a different folder, you will need to update the `package` at the top of
   > the generated file.
3. Migrate your code to the typed event captures:
   cap := typed.EventNameCapture("user_id", requiredProp1, requiredProp2)
   err := client.Enqueue(cap)

You can add optional properties through the option functions:
    cap := typed.EventNameCapture("user_id", required,
       typed.EventNameWithOptionalProp("value"))
"#
            ),
            Language::Python => format!(
                r#"
1. Save the generated file in your project (if not generated there already):
   mv {output_path} <your-project>/posthog_typed.py

2. Import and use the typed PostHog client:
   from posthog_typed import PosthogTyped

   client = PosthogTyped("<ph_project_api_key>", host="<ph_client_api_host>")

   # Use typed capture methods with full IDE autocomplete:
   client.capture_event_name(
       required_property="value",
       distinct_id="user_123",
   )

3. All standard Posthog methods are available:
   client.identify(...)
   client.capture(...)  # For untyped/dynamic events
   client.flush()
   client.shutdown()
"#
            ),
        }
    }

    /// Get all available languages
    fn all() -> Vec<Language> {
        vec![Language::TypeScript, Language::Golang, Language::Python]
    }

    /// Parse a language from a string identifier
    fn from_str(s: &str) -> Option<Language> {
        match s {
            "typescript" => Some(Language::TypeScript),
            "golang" => Some(Language::Golang),
            "python" => Some(Language::Python),
            _ => None,
        }
    }
}

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
        let json =
            serde_json::to_string_pretty(self).context("Failed to serialize schema config")?;
        fs::write("posthog.json", json).context("Failed to write posthog.json")?;
        Ok(())
    }

    /// Get language config for a specific language
    fn get_language(&self, language: Language) -> Option<&LanguageConfig> {
        self.languages.get(language.as_str())
    }

    /// Get output path for a language
    fn get_output_path(&self, language: Language) -> Option<String> {
        self.languages
            .get(language.as_str())
            .map(|l| l.output_path.clone())
    }

    /// Update language config, preserving other languages
    fn update_language(
        &mut self,
        language: Language,
        output_path: String,
        schema_hash: String,
        event_count: usize,
    ) {
        use chrono::Utc;

        self.languages.insert(
            language.as_str().to_string(),
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
struct DefinitionsResponse {
    content: String,
    event_count: usize,
    schema_hash: String,
}

pub fn pull(_host: Option<String>, output_override: Option<String>) -> Result<()> {
    // Select language
    let language = select_language()?;

    info!(
        "Fetching {} definitions from PostHog...",
        language.display_name()
    );

    // Get PH client
    let client = &context().client;

    // Determine output path
    let output_path = determine_output_path(language, output_override)?;

    // Fetch definitions from the server
    let response = fetch_definitions(client, language)?;

    info!(
        "✓ Fetched {} definitions for {} events",
        language.display_name(),
        response.event_count
    );

    // Check if schema has changed for this language
    let config = SchemaConfig::load();
    if let Some(lang_config) = config.get_language(language) {
        if lang_config.schema_hash == response.schema_hash {
            info!(
                "Schema unchanged for {} (hash: {})",
                language.as_str(),
                response.schema_hash
            );
            println!(
                "\n✓ {} schema is already up to date!",
                language.display_name()
            );
            println!("  No changes detected - skipping file write.");
            return Ok(());
        }
    }

    // Write language definitions to file
    info!("Writing {}...", output_path);

    // Create parent directories if they don't exist
    if let Some(parent) = Path::new(&output_path).parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .context(format!("Failed to create directory {}", parent.display()))?;
        }
    }

    fs::write(&output_path, &response.content).context(format!("Failed to write {output_path}"))?;
    info!("✓ Generated {}", output_path);

    // Update schema configuration for this language
    info!("Updating posthog.json...");
    let mut config = SchemaConfig::load();
    config.update_language(
        language,
        output_path.clone(),
        response.schema_hash,
        response.event_count,
    );
    config.save()?;
    info!("✓ Updated posthog.json");

    println!("✓ Schema sync complete!");
    println!("\nNext steps:");
    println!("{}", language.next_steps_text(&output_path));

    Ok(())
}

fn determine_output_path(language: Language, output_override: Option<String>) -> Result<String> {
    // If CLI override is provided, use it (and normalize it)
    if let Some(path) = output_override {
        return Ok(normalize_output_path(&path, language));
    }

    // Check if posthog.json exists and has an output_path for this language
    let config = SchemaConfig::load();
    if let Some(path) = config.get_output_path(language) {
        return Ok(path);
    }

    // Prompt user for output path
    let default_filename = language.default_output_path();
    let current_dir = std::env::current_dir()
        .ok()
        .and_then(|p| p.to_str().map(String::from))
        .unwrap_or_else(|| ".".to_string());

    let help_message = format!(
        "Your app will import PostHog from this file, so it should be accessible \
         throughout your codebase (e.g., src/lib/, app/lib/, or your project root). \
         This path will be saved in posthog.json and can be changed later. \
         Current directory: {current_dir}"
    );

    let path = Text::new(&format!(
        "Where should we save the {} typed PostHog module?",
        language.display_name()
    ))
    .with_default(default_filename)
    .with_help_message(&help_message)
    .prompt()
    .unwrap_or(default_filename.to_string());

    Ok(normalize_output_path(&path, language))
}

fn normalize_output_path(path: &str, language: Language) -> String {
    let path_obj = Path::new(path);

    // If it's a directory (existing or ends with slash), append default filename
    let should_append_filename =
        (path_obj.exists() && path_obj.is_dir()) || path.ends_with('/') || path.ends_with('\\');

    if should_append_filename {
        path_obj
            .join(language.default_output_path())
            .to_string_lossy()
            .into_owned()
    } else {
        path.to_string()
    }
}

pub fn status() -> Result<()> {
    // Check authentication
    println!("\nPostHog Schema Sync Status\n");

    println!("Authentication:");
    let config = context().config.clone();
    println!("  ✓ Authenticated");
    println!("  Host: {}", config.host);
    println!("  Project ID: {}", config.env_id);
    let masked_token = format!(
        "{}****{}",
        &config.api_key[..4],
        &config.api_key[config.api_key.len() - 4..]
    );
    println!("  Token: {masked_token}");

    println!();

    // Check schema status
    println!("Schema:");
    let config = SchemaConfig::load();

    if config.languages.is_empty() {
        println!("  ✗ No schemas synced");
        println!("  Run: posthog-cli exp schema pull");
    } else {
        println!("  ✓ Schemas synced\n");

        for (language_str, lang_config) in &config.languages {
            // Parse language to get display name, fallback to raw string if unknown
            let display = Language::from_str(language_str)
                .map(|l| l.display_name())
                .unwrap_or(language_str.as_str());

            println!("  {display}:");
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

fn fetch_definitions(client: &PHClient, language: Language) -> Result<DefinitionsResponse> {
    let url = format!("event_definitions/{}/", language.as_str());

    let response = client
        .get(client.project_url(&url)?)
        .send()
        .context(format!(
            "Failed to fetch {} definitions",
            language.display_name()
        ))?;

    if !response.status().is_success() {
        return Err(anyhow::anyhow!(
            "Failed to fetch {} definitions: HTTP {}",
            language.display_name(),
            response.status()
        ));
    }

    let json: DefinitionsResponse = response.json().context(format!(
        "Failed to parse {} definitions response",
        language.display_name()
    ))?;

    Ok(json)
}

fn select_language() -> Result<Language> {
    let languages = Language::all();

    if languages.len() == 1 {
        return Ok(languages[0]);
    }

    let language_strs: Vec<&str> = languages.iter().map(|l| l.display_name()).collect();
    let selected = Select::new("Which language would you like to download?", language_strs)
        .prompt()
        .context("Failed to select language")?;

    // Find the language that matches the selected display name
    languages
        .into_iter()
        .find(|l| l.display_name() == selected)
        .ok_or_else(|| anyhow::anyhow!("Invalid language selection"))
}
