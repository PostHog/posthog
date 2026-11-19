use anyhow::{Context, Result};
use inquire::{InquireError, Select, Text};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use tracing::info;

use crate::api::client::PHClient;
use crate::invocation_context::context;
use crate::utils::{describe_failed_response, redact_request_error, redact_url};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, clap::ValueEnum)]
pub enum Language {
    #[value(name = "typescript")]
    TypeScript,
    #[value(name = "golang")]
    Golang,
    #[value(name = "python")]
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
    fn next_steps_text(&self, output_path: &str, sdk: Option<Sdk>) -> String {
        let go_install = match sdk {
            Some(Sdk::Go(go)) => go.install_step(),
            Some(Sdk::TypeScript(_)) | None => GoSdk::V1.install_step(),
        };
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
   {go_install}
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

   client = PosthogTyped("<ph_project_token>", host="<ph_client_api_host>")

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

    /// The SDK a module is generated for when nothing chooses one.
    fn default_sdk(&self) -> Option<Sdk> {
        match self {
            Language::TypeScript => Some(Sdk::TypeScript(TypeScriptSdk::PosthogJs)),
            Language::Golang => Some(Sdk::Go(GoSdk::V1)),
            Language::Python => None,
        }
    }

    /// Whether posthog.json names the default SDK. TypeScript always did. Go names an SDK only
    /// once one is chosen, so an entry written before the choice existed stays as it is.
    fn records_default_sdk(&self) -> bool {
        match self {
            Language::TypeScript => true,
            Language::Golang | Language::Python => false,
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

/// What `--sdk` and the `sdk` entry in posthog.json choose. Each language owns its choices, so a
/// new one is added in one place and every `match` on it has to handle it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Sdk {
    TypeScript(TypeScriptSdk),
    Go(GoSdk),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, clap::ValueEnum)]
pub enum TypeScriptSdk {
    /// A typed posthog-js instance the app imports instead of posthog-js
    #[value(name = "posthog-js")]
    PosthogJs,
    /// Only the event types, with no imports, for posthog-react-native, posthog-node or any other SDK
    #[value(name = "none")]
    TypesOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, clap::ValueEnum)]
pub enum GoSdk {
    /// A Go package that imports posthog-go 1.x (github.com/posthog/posthog-go)
    #[value(name = "posthog-go")]
    V1,
    /// A Go package that imports posthog-go 2.x (github.com/posthog/posthog-go/v2)
    #[value(name = "posthog-go-v2")]
    V2,
}

impl GoSdk {
    /// Go treats each major from 2 on as its own module, so the package imports one of these.
    fn import_path(&self) -> &'static str {
        match self {
            GoSdk::V1 => "github.com/posthog/posthog-go",
            GoSdk::V2 => "github.com/posthog/posthog-go/v2",
        }
    }

    /// The install step shown after a pull.
    fn install_step(&self) -> String {
        match self {
            GoSdk::V1 => format!(
                "go get {}\n   > On posthog-go 2.x, pull with `--sdk posthog-go-v2` instead.",
                self.import_path()
            ),
            GoSdk::V2 => format!("go get {}", self.import_path()),
        }
    }
}

// `--sdk` takes the choices of every language as one list.
impl clap::ValueEnum for Sdk {
    fn value_variants<'a>() -> &'a [Self] {
        &[
            Sdk::TypeScript(TypeScriptSdk::PosthogJs),
            Sdk::TypeScript(TypeScriptSdk::TypesOnly),
            Sdk::Go(GoSdk::V1),
            Sdk::Go(GoSdk::V2),
        ]
    }

    fn to_possible_value(&self) -> Option<clap::builder::PossibleValue> {
        match self {
            Sdk::TypeScript(sdk) => sdk.to_possible_value(),
            Sdk::Go(sdk) => sdk.to_possible_value(),
        }
    }
}

impl Sdk {
    fn as_str(&self) -> &'static str {
        match self {
            Sdk::TypeScript(TypeScriptSdk::PosthogJs) => "posthog-js",
            Sdk::TypeScript(TypeScriptSdk::TypesOnly) => "none",
            Sdk::Go(GoSdk::V1) => "posthog-go",
            Sdk::Go(GoSdk::V2) => "posthog-go-v2",
        }
    }

    fn language(&self) -> Language {
        match self {
            Sdk::TypeScript(_) => Language::TypeScript,
            Sdk::Go(_) => Language::Golang,
        }
    }

    /// The error for a PostHog that predates this choice. A language's default has none: it is
    /// what such a PostHog generates anyway, so the CLI never asks for it.
    fn unsupported_message(&self) -> Option<&'static str> {
        match self {
            Sdk::TypeScript(TypeScriptSdk::PosthogJs) | Sdk::Go(GoSdk::V1) => None,
            Sdk::TypeScript(TypeScriptSdk::TypesOnly) => Some(
                "This PostHog instance cannot generate TypeScript types without an SDK yet. Update PostHog, or pull without --sdk none",
            ),
            Sdk::Go(GoSdk::V2) => Some(
                "This PostHog instance cannot generate Go for posthog-go 2.x yet. Update PostHog, or pull with --sdk posthog-go",
            ),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Module {
    language: Language,
    sdk: Option<Sdk>,
}

impl Module {
    fn types_only(&self) -> bool {
        self.sdk == Some(Sdk::TypeScript(TypeScriptSdk::TypesOnly))
    }

    fn display_name(&self) -> &'static str {
        if self.types_only() {
            "TypeScript (types only)"
        } else {
            self.language.display_name()
        }
    }

    fn default_output_path(&self) -> &'static str {
        if self.types_only() {
            "posthog-events.ts"
        } else {
            self.language.default_output_path()
        }
    }

    /// The `sdk` to ask PostHog for, with the error for a PostHog that ignores it. A language's
    /// default needs no query, so it also works on a PostHog that predates the choice.
    fn requested_sdk(&self) -> Option<(Sdk, &'static str)> {
        let sdk = self.sdk?;
        Some((sdk, sdk.unsupported_message()?))
    }

    fn next_steps_text(&self, output_path: &str) -> String {
        if !self.types_only() {
            return self.language.next_steps_text(output_path, self.sdk);
        }
        format!(
            r#"
1. Import the event types into your analytics code (no SDK dependency):
   import type {{ EventName, EventProperties }} from './{output_path}'
2. Use them to type the calls to your PostHog SDK, for example posthog-react-native:
   function track<K extends EventName>(event: K, properties: EventProperties<K>) {{
       posthog.capture(event, properties)
   }}
"#
        )
    }

    fn definitions_url(&self) -> String {
        let query = self
            .requested_sdk()
            .map(|(sdk, _)| format!("?sdk={}", sdk.as_str()))
            .unwrap_or_default();
        format!("event_definitions/{}/{query}", self.language.as_str())
    }
}

#[derive(Debug, Serialize, Deserialize, Default)]
struct SchemaConfig {
    languages: HashMap<String, LanguageConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct LanguageConfig {
    output_path: String,
    /// TypeScript and Go only. Kept as text, so a value this version does not know fails with a
    /// message instead of making the whole posthog.json unreadable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    sdk: Option<String>,
    schema_hash: String,
    updated_at: String,
    event_count: usize,
}

impl LanguageConfig {
    /// The SDK the saved module was generated for. An entry without `sdk` has the language's
    /// default, where the language records it.
    fn sdk(&self, language: Language) -> Result<Option<Sdk>> {
        let Some(value) = self.sdk.as_deref() else {
            return Ok(language
                .default_sdk()
                .filter(|_| language.records_default_sdk()));
        };
        match <Sdk as clap::ValueEnum>::from_str(value, false) {
            Ok(sdk) if sdk.language() == language => Ok(Some(sdk)),
            _ => anyhow::bail!(
                "posthog.json sets the {} sdk to \"{value}\", which this posthog-cli does not know. Update posthog-cli, or pass --sdk",
                language.display_name()
            ),
        }
    }
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
        module: Module,
        output_path: String,
        schema_hash: String,
        event_count: usize,
    ) {
        use chrono::Utc;

        self.languages.insert(
            module.language.as_str().to_string(),
            LanguageConfig {
                output_path,
                sdk: module.sdk.map(|sdk| sdk.as_str().to_string()),
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
    #[serde(default)]
    sdk: Option<String>,
}

pub fn pull(
    _host: Option<String>,
    output_override: Option<String>,
    language: Option<Language>,
    sdk: Option<Sdk>,
) -> Result<()> {
    let language = match language {
        Some(language) => language,
        None => select_language()?,
    };
    if let Some(sdk) = sdk.filter(|sdk| sdk.language() != language) {
        anyhow::bail!(
            "--sdk {} only applies to {}. Pass --language {} too",
            sdk.as_str(),
            sdk.language().display_name(),
            sdk.language().as_str()
        );
    }

    let config = SchemaConfig::load();
    let saved = config.get_language(language);
    let module = Module {
        language,
        sdk: match (sdk, saved, language) {
            (Some(sdk), _, _) => Some(sdk),
            (None, Some(saved), _) => saved.sdk(language)?,
            (None, None, Language::TypeScript) => Some(Sdk::TypeScript(select_typescript_sdk()?)),
            (None, None, Language::Golang | Language::Python) => None,
        },
    };

    info!(
        "Fetching {} definitions from PostHog...",
        module.display_name()
    );

    // Get PH client
    let client = &context().client;

    // Determine output path
    let output_path = determine_output_path(module, output_override)?;

    // Fetch definitions from the server
    let response = fetch_definitions(client, module)?;

    info!(
        "✓ Fetched {} definitions for {} events",
        module.display_name(),
        response.event_count
    );

    // Check if schema has changed for this language, and that it still wraps the same SDK
    if let Some(lang_config) = saved {
        let same_sdk = match lang_config.sdk(language) {
            Ok(saved_sdk) => {
                effective_sdk(language, saved_sdk) == effective_sdk(language, module.sdk)
            }
            Err(_) => false,
        };
        if same_sdk && lang_config.schema_hash == response.schema_hash {
            info!(
                "Schema unchanged for {} (hash: {})",
                language.as_str(),
                response.schema_hash
            );
            crate::safe_println!(
                "\n✓ {} schema is already up to date!",
                module.display_name()
            );
            crate::safe_println!("  No changes detected - skipping file write.");
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
        module,
        output_path.clone(),
        response.schema_hash,
        response.event_count,
    );
    config.save()?;
    info!("✓ Updated posthog.json");

    crate::safe_println!("✓ Schema sync complete!");
    crate::safe_println!("\nNext steps:");
    crate::safe_println!("{}", module.next_steps_text(&output_path));

    Ok(())
}

fn determine_output_path(module: Module, output_override: Option<String>) -> Result<String> {
    // If CLI override is provided, use it (and normalize it)
    if let Some(path) = output_override {
        return Ok(normalize_output_path(&path, module));
    }

    // Check if posthog.json exists and has an output_path for this language
    let config = SchemaConfig::load();
    if let Some(path) = config.get_output_path(module.language) {
        return Ok(path);
    }

    // Prompt user for output path
    let default_filename = module.default_output_path();
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
        "Where should we save the {} module?",
        module.display_name()
    ))
    .with_default(default_filename)
    .with_help_message(&help_message)
    .prompt()
    .unwrap_or(default_filename.to_string());

    Ok(normalize_output_path(&path, module))
}

fn normalize_output_path(path: &str, module: Module) -> String {
    let path_obj = Path::new(path);

    // If it's a directory (existing or ends with slash), append default filename
    let should_append_filename =
        (path_obj.exists() && path_obj.is_dir()) || path.ends_with('/') || path.ends_with('\\');

    if should_append_filename {
        path_obj
            .join(module.default_output_path())
            .to_string_lossy()
            .into_owned()
    } else {
        path.to_string()
    }
}

pub fn status() -> Result<()> {
    // Check authentication
    crate::safe_println!("\nPostHog Schema Sync Status\n");

    crate::safe_println!("Authentication:");
    let config = context().config.clone();
    crate::safe_println!("  ✓ Authenticated");
    crate::safe_println!(
        "  Host: {}",
        redact_url(&reqwest::Url::parse(&config.host)?)
    );
    crate::safe_println!("  Project ID: {}", config.env_id);
    let masked_token = format!(
        "{}****{}",
        &config.api_key[..4],
        &config.api_key[config.api_key.len() - 4..]
    );
    crate::safe_println!("  Token: {masked_token}");

    crate::safe_println!();

    // Check schema status
    crate::safe_println!("Schema:");
    let config = SchemaConfig::load();

    if config.languages.is_empty() {
        crate::safe_println!("  ✗ No schemas synced");
        crate::safe_println!("  Run: posthog-cli exp schema pull");
    } else {
        crate::safe_println!("  ✓ Schemas synced\n");

        for (language_str, lang_config) in &config.languages {
            // Parse language to get display name, fallback to raw string if unknown
            let display = Language::from_str(language_str)
                .map(|language| {
                    Module {
                        language,
                        sdk: lang_config.sdk(language).ok().flatten(),
                    }
                    .display_name()
                })
                .unwrap_or(language_str.as_str());

            crate::safe_println!("  {display}:");
            crate::safe_println!("    Hash: {}", lang_config.schema_hash);
            crate::safe_println!("    Updated: {}", lang_config.updated_at);
            crate::safe_println!("    Events: {}", lang_config.event_count);

            if Path::new(&lang_config.output_path).exists() {
                crate::safe_println!("    File: ✓ {}", lang_config.output_path);
            } else {
                crate::safe_println!("    File: ! {} (missing)", lang_config.output_path);
            }
            crate::safe_println!();
        }
    }

    crate::safe_println!();

    Ok(())
}

fn fetch_definitions(client: &PHClient, module: Module) -> Result<DefinitionsResponse> {
    let url = module.definitions_url();

    let response = client
        .get(client.project_url(&url)?)
        .send()
        .map_err(redact_request_error)
        .context(format!(
            "Failed to fetch {} definitions",
            module.display_name()
        ))?;

    if !response.status().is_success() {
        return Err(anyhow::anyhow!(
            "Failed to fetch {} definitions: {}",
            module.display_name(),
            describe_failed_response(response)
        ));
    }

    let json: DefinitionsResponse = response.json().context(format!(
        "Failed to parse {} definitions response",
        module.display_name()
    ))?;

    // A PostHog that predates an `sdk` choice ignores the query and sends the default module, without saying which SDK
    if let Some((sdk, unsupported)) = module.requested_sdk() {
        if json.sdk.as_deref() != Some(sdk.as_str()) {
            anyhow::bail!(unsupported);
        }
    }

    Ok(json)
}

/// An entry with no `sdk` has the same module as one that names the language's default.
fn effective_sdk(language: Language, sdk: Option<Sdk>) -> Option<Sdk> {
    sdk.or(language.default_sdk())
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

/// Without a terminal, the prompt fails and the module wraps posthog-js
fn select_typescript_sdk() -> Result<TypeScriptSdk> {
    let options = vec![
        "posthog-js: wrap it so capture() checks your events",
        "Another SDK, such as posthog-react-native: only the event types",
    ];
    match Select::new("Which PostHog SDK does this app use?", options.clone()).prompt() {
        Ok(selected) if selected == options[1] => Ok(TypeScriptSdk::TypesOnly),
        Ok(_) | Err(InquireError::NotTTY) => Ok(TypeScriptSdk::PosthogJs),
        Err(err) => Err(err).context("Failed to select the TypeScript SDK"),
    }
}
