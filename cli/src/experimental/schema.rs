use anyhow::{Context, Result};
use clap::{Args, Subcommand, ValueEnum};
use inquire::{Select, Text};
use reqwest::Url;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum LocalLanguage {
    #[value(alias = "ts")]
    Typescript,
    #[value(alias = "go", alias = "golang")]
    Golang,
    Python,
}

impl LocalLanguage {
    fn as_config_key(&self) -> &'static str {
        match self {
            LocalLanguage::Typescript => "typescript",
            LocalLanguage::Golang => "golang",
            LocalLanguage::Python => "python",
        }
    }

    fn display_name(&self) -> &'static str {
        match self {
            LocalLanguage::Typescript => "TypeScript",
            LocalLanguage::Golang => "Go",
            LocalLanguage::Python => "Python",
        }
    }

    fn default_output_path(&self) -> &'static str {
        match self {
            LocalLanguage::Typescript => "posthog-events-typed.ts",
            LocalLanguage::Golang => "posthog-events-typed.go",
            LocalLanguage::Python => "posthog_events_typed.py",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum Baseline {
    #[value(name = "posthog_growth_v0", alias = "posthog-growth-v0")]
    PosthogGrowthV0,
    Blank,
    Aarrr,
    #[value(name = "activation_revenue", alias = "activation-revenue")]
    ActivationRevenue,
}

impl Baseline {
    fn as_str(&self) -> &'static str {
        match self {
            Baseline::PosthogGrowthV0 => "posthog_growth_v0",
            Baseline::Blank => "blank",
            Baseline::Aarrr => "aarrr",
            Baseline::ActivationRevenue => "activation_revenue",
        }
    }
}

#[derive(Subcommand, Debug)]
pub enum LocalSchemaCommand {
    /// Create a local tracking plan and save local schema config
    Init(InitArgs),
    /// Validate a local tracking plan
    Validate(SourceArgs),
    /// Generate typed helpers from a local tracking plan
    Generate(GenerateArgs),
    /// Push a local tracking plan to PostHog
    Push(PushArgs),
    /// Compare a local tracking plan with PostHog
    Diff(DiffArgs),
    /// Detect repo language hints for local schema setup
    Detect,
}

impl LocalSchemaCommand {
    pub fn requires_context(&self) -> bool {
        matches!(
            self,
            LocalSchemaCommand::Push(_) | LocalSchemaCommand::Diff(DiffArgs { posthog: true, .. })
        )
    }
}

#[derive(Args, Debug)]
pub struct InitArgs {
    /// Local tracking plan path
    #[arg(long, default_value = "posthog.events.yaml")]
    source: String,
    /// Language to generate typed helpers for
    #[arg(short = 'l', long, value_enum)]
    lang: Option<LocalLanguage>,
    /// Generated output path
    #[arg(long)]
    out: Option<String>,
    /// Starter event taxonomy
    #[arg(long, value_enum, default_value = "posthog_growth_v0")]
    baseline: Baseline,
    /// Event naming convention (currently only snake_case_past_tense is supported)
    #[arg(
        long,
        default_value = "snake_case_past_tense",
        value_parser = ["snake_case_past_tense"],
        hide = true
    )]
    naming: String,
    /// Overwrite an existing source file
    #[arg(long, default_value = "false")]
    force: bool,
}

#[derive(Args, Debug)]
pub struct SourceArgs {
    /// Local tracking plan path
    #[arg(long, default_value = "posthog.events.yaml")]
    source: String,
}

#[derive(Args, Debug)]
pub struct GenerateArgs {
    /// Local tracking plan path
    #[arg(long, default_value = "posthog.events.yaml")]
    source: String,
    /// Language to generate typed helpers for
    #[arg(long, value_enum)]
    lang: LocalLanguage,
    /// Generated output path
    #[arg(long)]
    out: Option<String>,
}

#[derive(Args, Debug)]
pub struct PushArgs {
    /// Local tracking plan path
    #[arg(long, default_value = "posthog.events.yaml")]
    source: String,
    /// Show planned writes without changing PostHog
    #[arg(long, default_value = "false")]
    dry_run: bool,
}

#[derive(Args, Debug)]
pub struct DiffArgs {
    /// Local tracking plan path
    #[arg(long, default_value = "posthog.events.yaml")]
    source: String,
    /// Compare the local tracking plan with PostHog
    #[arg(long, default_value = "false")]
    posthog: bool,
}

#[derive(Debug, Serialize, Deserialize, Default)]
struct LocalSchemaConfig {
    #[serde(default)]
    tracking_plan: Option<TrackingPlanConfig>,
    #[serde(default)]
    languages: HashMap<String, LanguageConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct TrackingPlanConfig {
    source_path: String,
    baseline: String,
    naming: String,
    schema_hash: String,
    updated_at: String,
    event_count: usize,
}

impl LocalSchemaConfig {
    fn load() -> Self {
        let content = fs::read_to_string("posthog.json").ok();
        content
            .and_then(|c| serde_json::from_str(&c).ok())
            .unwrap_or_default()
    }

    fn save(&self) -> Result<()> {
        let json =
            serde_json::to_string_pretty(self).context("Failed to serialize posthog.json")?;
        fs::write("posthog.json", json).context("Failed to write posthog.json")?;
        Ok(())
    }

    fn update_tracking_plan(&mut self, args: &InitArgs, hash: String, event_count: usize) {
        use chrono::Utc;

        self.tracking_plan = Some(TrackingPlanConfig {
            source_path: args.source.clone(),
            baseline: args.baseline.as_str().to_string(),
            naming: args.naming.clone(),
            schema_hash: hash,
            updated_at: Utc::now().to_rfc3339(),
            event_count,
        });
    }

    fn update_local_language(
        &mut self,
        language: LocalLanguage,
        output_path: String,
        schema_hash: String,
        event_count: usize,
    ) {
        use chrono::Utc;

        self.languages.insert(
            language.as_config_key().to_string(),
            LanguageConfig {
                output_path,
                schema_hash,
                updated_at: Utc::now().to_rfc3339(),
                event_count,
            },
        );
    }
}

#[derive(Debug, Serialize, Deserialize)]
struct TrackingPlan {
    version: u32,
    naming: NamingRules,
    #[serde(default)]
    baselines: Vec<String>,
    #[serde(default)]
    property_groups: BTreeMap<String, PropertyGroup>,
    #[serde(default)]
    events: BTreeMap<String, EventSpec>,
}

#[derive(Debug, Serialize, Deserialize)]
struct NamingRules {
    event: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct PropertyGroup {
    description: String,
    #[serde(default)]
    properties: BTreeMap<String, PropertySpec>,
}

#[derive(Debug, Serialize, Deserialize)]
struct EventSpec {
    #[serde(rename = "type")]
    category: String,
    description: String,
    owner: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    property_groups: Vec<String>,
    #[serde(default)]
    properties: BTreeMap<String, PropertySpec>,
    #[serde(default)]
    primary_property: Option<String>,
    status: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct PropertySpec {
    #[serde(rename = "type")]
    kind: PropertyKind,
    #[serde(default)]
    required: bool,
    #[serde(default)]
    description: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum PropertyKind {
    String,
    Numeric,
    Boolean,
    DateTime,
    Object,
}

pub fn run_local(cmd: LocalSchemaCommand) -> Result<()> {
    match cmd {
        LocalSchemaCommand::Init(args) => init_local(args),
        LocalSchemaCommand::Validate(args) => {
            let plan = read_tracking_plan(&args.source)?;
            validate_tracking_plan(&plan)?;
            println!(
                "✓ {} is valid ({} events, {} property groups)",
                args.source,
                plan.events.len(),
                plan.property_groups.len()
            );
            Ok(())
        }
        LocalSchemaCommand::Generate(args) => generate_local(args),
        LocalSchemaCommand::Push(args) => push_local(args),
        LocalSchemaCommand::Diff(args) => diff_local(args),
        LocalSchemaCommand::Detect => detect_local(),
    }
}

fn init_local(args: InitArgs) -> Result<()> {
    if Path::new(&args.source).exists() && !args.force {
        return Err(anyhow::anyhow!(
            "{} already exists. Pass --force to overwrite it.",
            args.source
        ));
    }

    let plan = starter_plan(args.baseline, &args.naming);
    let yaml = serde_yaml::to_string(&plan).context("Failed to serialize tracking plan")?;
    fs::write(&args.source, yaml).context(format!("Failed to write {}", args.source))?;

    let plan = read_tracking_plan(&args.source)?;
    validate_tracking_plan(&plan)?;
    let hash = hash_plan(&plan)?;

    let mut config = LocalSchemaConfig::load();
    config.update_tracking_plan(&args, hash.clone(), plan.events.len());

    let detected_languages = detect_local_languages()?;
    let selected_language = args.lang.or_else(|| {
        if detected_languages.len() == 1 {
            detected_languages.first().copied()
        } else {
            None
        }
    });

    if let Some(lang) = selected_language {
        let out = args
            .out
            .clone()
            .unwrap_or_else(|| lang.default_output_path().to_string());
        config.update_local_language(lang, out.clone(), hash.clone(), plan.events.len());
        write_generated_file(&plan, lang, &out)?;
        println!(
            "✓ Generated {} typed helpers at {}",
            lang.display_name(),
            out
        );
    } else {
        if detected_languages.is_empty() {
            println!("! No TypeScript, Go, or Python project files detected; skipped typed helper generation.");
        } else {
            println!("! Multiple language hints detected; skipped typed helper generation.");
            println!(
                "  Detected: {}",
                language_names(&detected_languages).join(", ")
            );
        }
        println!("  Run `posthog-cli schema generate --lang <language>` after choosing an output.");
    }

    config.save()?;
    println!(
        "✓ Created {} ({} events, baseline: {})",
        args.source,
        plan.events.len(),
        args.baseline.as_str()
    );
    println!("✓ Updated posthog.json");

    Ok(())
}

fn generate_local(args: GenerateArgs) -> Result<()> {
    let plan = read_tracking_plan(&args.source)?;
    validate_tracking_plan(&plan)?;

    let mut config = LocalSchemaConfig::load();
    let output_path = args.out.unwrap_or_else(|| {
        config
            .languages
            .get(args.lang.as_config_key())
            .map(|c| c.output_path.clone())
            .unwrap_or_else(|| args.lang.default_output_path().to_string())
    });

    write_generated_file(&plan, args.lang, &output_path)?;

    config.update_local_language(
        args.lang,
        output_path.clone(),
        hash_plan(&plan)?,
        plan.events.len(),
    );
    config.save()?;

    println!(
        "✓ Generated {} typed helpers from {}",
        args.lang.display_name(),
        args.source
    );
    println!("  Output: {output_path}");
    println!("  Events: {}", plan.events.len());
    Ok(())
}

fn push_local(args: PushArgs) -> Result<()> {
    let plan = read_tracking_plan(&args.source)?;
    validate_tracking_plan(&plan)?;
    let desired = build_remote_plan(&plan)?;
    let client = &context().client;
    let remote = fetch_remote_state(client)?;
    let changes = diff_remote_state(&desired, &remote);

    if args.dry_run {
        if changes.is_empty() {
            println!("No changes detected");
        } else {
            println!("Planned schema writes:");
            print_changes(&changes);
        }
        return Ok(());
    }

    if changes.is_empty() {
        println!("No changes detected");
        return Ok(());
    }

    apply_remote_plan(client, &desired, &remote)?;
    let refreshed = fetch_remote_state(client)?;
    let remaining = diff_remote_state(&desired, &refreshed);
    if remaining.is_empty() {
        println!("✓ Schema push complete");
        println!("No drift detected");
        Ok(())
    } else {
        Err(anyhow::anyhow!(
            "Schema push completed, but drift remains:\n- {}",
            remaining
                .iter()
                .map(SyncChange::describe)
                .collect::<Vec<_>>()
                .join("\n- ")
        ))
    }
}

fn diff_local(args: DiffArgs) -> Result<()> {
    if !args.posthog {
        return Err(anyhow::anyhow!(
            "Only PostHog diff is supported. Run `posthog-cli schema diff --posthog`."
        ));
    }

    let plan = read_tracking_plan(&args.source)?;
    validate_tracking_plan(&plan)?;
    let desired = build_remote_plan(&plan)?;
    let remote = fetch_remote_state(&context().client)?;
    let changes = diff_remote_state(&desired, &remote);

    if changes.is_empty() {
        println!("No drift detected");
    } else {
        println!("Drift detected:");
        print_changes(&changes);
    }
    Ok(())
}

fn print_changes(changes: &[SyncChange]) {
    for change in changes {
        println!("{}", change.describe());
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DesiredRemotePlan {
    events: BTreeMap<String, DesiredEvent>,
    property_groups: BTreeMap<String, DesiredPropertyGroup>,
    event_schema_links: BTreeSet<(String, String)>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DesiredEvent {
    name: String,
    description: String,
    tags: Vec<String>,
    primary_property: Option<String>,
    status: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DesiredPropertyGroup {
    name: String,
    description: String,
    properties: BTreeMap<String, DesiredProperty>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DesiredProperty {
    property_type: String,
    is_required: bool,
    description: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RemoteState {
    events: BTreeMap<String, RemoteEvent>,
    property_groups: BTreeMap<String, RemotePropertyGroup>,
    event_schema_links: BTreeMap<(String, String), String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RemoteEvent {
    id: String,
    name: String,
    description: Option<String>,
    tags: Vec<String>,
    primary_property: Option<String>,
    status: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RemotePropertyGroup {
    id: String,
    name: String,
    description: String,
    properties: BTreeMap<String, DesiredProperty>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum SyncChange {
    CreateEvent(String),
    UpdateEvent(String),
    CreatePropertyGroup(String),
    UpdatePropertyGroup(String),
    AttachEventSchema {
        event: String,
        property_group: String,
    },
    UnexpectedEventSchema {
        event: String,
        property_group: String,
    },
}

impl SyncChange {
    fn describe(&self) -> String {
        match self {
            SyncChange::CreateEvent(name) => format!("Create event definition: {name}"),
            SyncChange::UpdateEvent(name) => format!("Update event definition: {name}"),
            SyncChange::CreatePropertyGroup(name) => format!("Create property group: {name}"),
            SyncChange::UpdatePropertyGroup(name) => format!("Update property group: {name}"),
            SyncChange::AttachEventSchema {
                event,
                property_group,
            } => format!("Attach event schema properties: {event} -> {property_group}"),
            SyncChange::UnexpectedEventSchema {
                event,
                property_group,
            } => format!("Remove event schema properties: {event} -> {property_group}"),
        }
    }
}

fn build_remote_plan(plan: &TrackingPlan) -> Result<DesiredRemotePlan> {
    let mut property_groups = BTreeMap::new();
    let mut event_schema_links = BTreeSet::new();
    let mut events = BTreeMap::new();

    for (name, group) in &plan.property_groups {
        property_groups.insert(
            name.clone(),
            DesiredPropertyGroup {
                name: name.clone(),
                description: group.description.clone(),
                properties: group
                    .properties
                    .iter()
                    .map(|(prop_name, prop)| (prop_name.clone(), desired_property(prop)))
                    .collect(),
            },
        );
    }

    for (event_name, event) in &plan.events {
        events.insert(
            event_name.clone(),
            DesiredEvent {
                name: event_name.clone(),
                description: event.description.clone(),
                tags: event.tags.clone(),
                primary_property: event.primary_property.clone(),
                status: event.status.clone(),
            },
        );

        for group_name in &event.property_groups {
            event_schema_links.insert((event_name.clone(), group_name.clone()));
        }

        if !event.properties.is_empty() {
            let group_name = event_property_group_name(event_name);
            if property_groups.contains_key(&group_name) {
                return Err(anyhow::anyhow!(
                    "Event `{event_name}` needs generated property group `{group_name}`, but that group already exists"
                ));
            }
            property_groups.insert(
                group_name.clone(),
                DesiredPropertyGroup {
                    name: group_name.clone(),
                    description: format!("Event-specific properties for {event_name}."),
                    properties: event
                        .properties
                        .iter()
                        .map(|(prop_name, prop)| (prop_name.clone(), desired_property(prop)))
                        .collect(),
                },
            );
            event_schema_links.insert((event_name.clone(), group_name));
        }
    }

    Ok(DesiredRemotePlan {
        events,
        property_groups,
        event_schema_links,
    })
}

fn event_property_group_name(event_name: &str) -> String {
    format!("{event_name}_properties")
}

fn desired_property(prop: &PropertySpec) -> DesiredProperty {
    DesiredProperty {
        property_type: remote_property_type(&prop.kind).to_string(),
        is_required: prop.required,
        description: prop.description.clone().unwrap_or_default(),
    }
}

fn remote_property_type(kind: &PropertyKind) -> &'static str {
    match kind {
        PropertyKind::String => "String",
        PropertyKind::Numeric => "Numeric",
        PropertyKind::Boolean => "Boolean",
        PropertyKind::DateTime => "DateTime",
        PropertyKind::Object => "Object",
    }
}

fn diff_remote_state(desired: &DesiredRemotePlan, remote: &RemoteState) -> Vec<SyncChange> {
    let mut changes = Vec::new();

    for (name, group) in &desired.property_groups {
        match remote.property_groups.get(name) {
            None => changes.push(SyncChange::CreatePropertyGroup(name.clone())),
            Some(remote_group) if !property_groups_match(group, remote_group) => {
                changes.push(SyncChange::UpdatePropertyGroup(name.clone()));
            }
            Some(_) => {}
        }
    }

    for (name, event) in &desired.events {
        match remote.events.get(name) {
            None => changes.push(SyncChange::CreateEvent(name.clone())),
            Some(remote_event) if !events_match(event, remote_event) => {
                changes.push(SyncChange::UpdateEvent(name.clone()));
            }
            Some(_) => {}
        }
    }

    for (event, property_group) in &desired.event_schema_links {
        if !remote
            .event_schema_links
            .contains_key(&(event.clone(), property_group.clone()))
        {
            changes.push(SyncChange::AttachEventSchema {
                event: event.clone(),
                property_group: property_group.clone(),
            });
        }
    }

    for (event, property_group) in remote.event_schema_links.keys() {
        if desired.events.contains_key(event)
            && !desired
                .event_schema_links
                .contains(&(event.clone(), property_group.clone()))
        {
            changes.push(SyncChange::UnexpectedEventSchema {
                event: event.clone(),
                property_group: property_group.clone(),
            });
        }
    }

    changes
}

fn property_groups_match(desired: &DesiredPropertyGroup, remote: &RemotePropertyGroup) -> bool {
    desired.description == remote.description && desired.properties == remote.properties
}

fn events_match(desired: &DesiredEvent, remote: &RemoteEvent) -> bool {
    normalize_optional(desired.primary_property.as_deref())
        == normalize_optional(remote.primary_property.as_deref())
        && sorted_tags(&desired.tags) == sorted_tags(&remote.tags)
        && desired.status == remote.status
        && normalize_optional(Some(&desired.description))
            == normalize_optional(remote.description.as_deref())
}

fn normalize_optional(value: Option<&str>) -> Option<String> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn sorted_tags(tags: &[String]) -> Vec<String> {
    let mut tags = tags.to_vec();
    tags.sort();
    tags.dedup();
    tags
}

fn fetch_remote_state(client: &PHClient) -> Result<RemoteState> {
    let events: Vec<EventDefinitionResponse> =
        fetch_paginated(client, "event_definitions/?event_type=event")?;
    let property_groups: Vec<SchemaPropertyGroupResponse> =
        fetch_paginated(client, "schema_property_groups/")?;
    let event_schemas: Vec<EventSchemaResponse> = fetch_paginated(client, "event_schemas/")?;

    let events_by_id: BTreeMap<String, String> = events
        .iter()
        .map(|event| (event.id.clone(), event.name.clone()))
        .collect();
    let property_groups_by_id: BTreeMap<String, String> = property_groups
        .iter()
        .map(|group| (group.id.clone(), group.name.clone()))
        .collect();

    let event_schema_links = event_schemas
        .into_iter()
        .filter_map(|schema| {
            let event_id = schema.event_definition.id()?;
            let property_group_id = schema
                .property_group
                .as_ref()
                .map(|group| group.id.clone())?;
            let event_name = events_by_id.get(&event_id)?;
            let property_group_name = property_groups_by_id.get(&property_group_id)?;
            Some((
                (event_name.clone(), property_group_name.clone()),
                schema.id.clone(),
            ))
        })
        .collect();

    Ok(RemoteState {
        events: events
            .into_iter()
            .map(|event| {
                let status = if event.hidden.unwrap_or(false) {
                    "deprecated"
                } else if event.verified.unwrap_or(false) {
                    "verified"
                } else {
                    "draft"
                }
                .to_string();
                (
                    event.name.clone(),
                    RemoteEvent {
                        id: event.id,
                        name: event.name,
                        description: event.description,
                        tags: event.tags,
                        primary_property: event.primary_property,
                        status,
                    },
                )
            })
            .collect(),
        property_groups: property_groups
            .into_iter()
            .map(|group| {
                (
                    group.name.clone(),
                    RemotePropertyGroup {
                        id: group.id,
                        name: group.name,
                        description: group.description.unwrap_or_default(),
                        properties: group
                            .properties
                            .into_iter()
                            .map(|prop| {
                                (
                                    prop.name,
                                    DesiredProperty {
                                        property_type: prop.property_type,
                                        is_required: prop.is_required,
                                        description: prop.description.unwrap_or_default(),
                                    },
                                )
                            })
                            .collect(),
                    },
                )
            })
            .collect(),
        event_schema_links,
    })
}

fn apply_remote_plan(
    client: &PHClient,
    desired: &DesiredRemotePlan,
    remote: &RemoteState,
) -> Result<()> {
    for (name, group) in &desired.property_groups {
        match remote.property_groups.get(name) {
            Some(remote_group) if property_groups_match(group, remote_group) => {}
            Some(remote_group) => {
                request_json(
                    client,
                    "PUT",
                    &format!("schema_property_groups/{}/", remote_group.id),
                    property_group_payload(group),
                )?;
                println!("Update property group: {name}");
            }
            None => {
                request_json(
                    client,
                    "POST",
                    "schema_property_groups/",
                    property_group_payload(group),
                )?;
                println!("Create property group: {name}");
            }
        }
    }

    for (name, event) in &desired.events {
        match remote.events.get(name) {
            Some(remote_event) if events_match(event, remote_event) => {}
            Some(remote_event) => {
                request_json(
                    client,
                    "PATCH",
                    &format!("event_definitions/{}/", remote_event.id),
                    event_definition_payload(event),
                )?;
                println!("Update event definition: {name}");
            }
            None => {
                request_json(
                    client,
                    "POST",
                    "event_definitions/",
                    event_definition_payload(event),
                )?;
                println!("Create event definition: {name}");
            }
        }
    }

    let refreshed = fetch_remote_state(client)?;
    for (event_name, property_group_name) in &desired.event_schema_links {
        if refreshed
            .event_schema_links
            .contains_key(&(event_name.clone(), property_group_name.clone()))
        {
            continue;
        }
        let event = refreshed.events.get(event_name).ok_or_else(|| {
            anyhow::anyhow!("Event definition `{event_name}` was not found after sync")
        })?;
        let property_group = refreshed
            .property_groups
            .get(property_group_name)
            .ok_or_else(|| {
                anyhow::anyhow!("Property group `{property_group_name}` was not found after sync")
            })?;
        request_json(
            client,
            "POST",
            "event_schemas/",
            json!({
                "event_definition": event.id,
                "property_group_id": property_group.id,
            }),
        )?;
        println!("Attach event schema properties: {event_name} -> {property_group_name}");
    }

    for ((event_name, property_group_name), schema_id) in &refreshed.event_schema_links {
        if desired.events.contains_key(event_name)
            && !desired
                .event_schema_links
                .contains(&(event_name.clone(), property_group_name.clone()))
        {
            request_empty(client, "DELETE", &format!("event_schemas/{schema_id}/"))?;
            println!("Remove event schema properties: {event_name} -> {property_group_name}");
        }
    }

    Ok(())
}

fn property_group_payload(group: &DesiredPropertyGroup) -> Value {
    json!({
        "name": group.name,
        "description": group.description,
        "properties": group
            .properties
            .iter()
            .map(|(name, prop)| {
                json!({
                    "name": name,
                    "property_type": prop.property_type,
                    "is_required": prop.is_required,
                    "is_optional_in_types": false,
                    "description": prop.description,
                })
            })
            .collect::<Vec<_>>(),
    })
}

fn event_definition_payload(event: &DesiredEvent) -> Value {
    let verified = event.status == "verified";
    let hidden = event.status == "deprecated";
    json!({
        "name": event.name,
        "description": event.description,
        "tags": event.tags,
        "primary_property": event.primary_property,
        "verified": verified,
        "hidden": hidden,
    })
}

fn request_json(client: &PHClient, method: &str, path: &str, payload: Value) -> Result<Value> {
    let url = client.project_url(path)?;
    let request = match method {
        "POST" => client.post(url),
        "PUT" => client.put(url),
        "PATCH" => client.patch(url),
        _ => return Err(anyhow::anyhow!("Unsupported HTTP method `{method}`")),
    };
    let response = request
        .json(&payload)
        .send()
        .context(format!("Failed to {method} {path}"))?;
    let status = response.status();
    if !status.is_success() {
        let body = response.text().unwrap_or_else(|_| String::new());
        return Err(anyhow::anyhow!(
            "PostHog API request failed: {method} {path} returned {status}: {body}"
        ));
    }
    response
        .json::<Value>()
        .context(format!("Failed to parse {method} {path} response"))
}

fn request_empty(client: &PHClient, method: &str, path: &str) -> Result<()> {
    let url = client.project_url(path)?;
    let request = match method {
        "DELETE" => client.delete(url),
        _ => return Err(anyhow::anyhow!("Unsupported HTTP method `{method}`")),
    };
    let response = request
        .send()
        .context(format!("Failed to {method} {path}"))?;
    let status = response.status();
    if !status.is_success() {
        let body = response.text().unwrap_or_else(|_| String::new());
        return Err(anyhow::anyhow!(
            "PostHog API request failed: {method} {path} returned {status}: {body}"
        ));
    }
    Ok(())
}

#[derive(Debug, Deserialize)]
struct PaginatedResponse<T> {
    results: Vec<T>,
    next: Option<String>,
}

fn fetch_paginated<T>(client: &PHClient, path: &str) -> Result<Vec<T>>
where
    T: serde::de::DeserializeOwned,
{
    let mut url = client.project_url(path)?;
    let allowed_origin = client.project_url("")?;
    let mut results = Vec::new();

    loop {
        let response = client
            .get(url.clone())
            .send()
            .context(format!("Failed to fetch {path}"))?;
        let status = response.status();
        if !status.is_success() {
            let body = response.text().unwrap_or_else(|_| String::new());
            return Err(anyhow::anyhow!(
                "PostHog API request failed: GET {url} returned {status}: {body}"
            ));
        }
        let page: PaginatedResponse<T> = response
            .json()
            .context(format!("Failed to parse {path} response"))?;
        results.extend(page.results);
        match page.next {
            Some(next_url) => {
                let parsed = Url::parse(&next_url)
                    .context(format!("Failed to parse next page URL `{next_url}`"))?;
                if !same_origin(&parsed, &allowed_origin) {
                    return Err(anyhow::anyhow!(
                        "Pagination next URL `{next_url}` does not match the configured PostHog host"
                    ));
                }
                url = parsed;
            }
            None => break,
        }
    }

    Ok(results)
}

fn same_origin(left: &Url, right: &Url) -> bool {
    left.scheme() == right.scheme()
        && left.host_str() == right.host_str()
        && left.port_or_known_default() == right.port_or_known_default()
}

#[derive(Debug, Deserialize)]
struct EventDefinitionResponse {
    id: String,
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    primary_property: Option<String>,
    #[serde(default)]
    verified: Option<bool>,
    #[serde(default)]
    hidden: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct SchemaPropertyGroupResponse {
    id: String,
    name: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    properties: Vec<SchemaPropertyGroupPropertyResponse>,
}

#[derive(Debug, Deserialize)]
struct SchemaPropertyGroupPropertyResponse {
    name: String,
    property_type: String,
    #[serde(default)]
    is_required: bool,
    #[serde(default)]
    description: Option<String>,
}

#[derive(Debug, Deserialize)]
struct EventSchemaResponse {
    id: String,
    event_definition: IdReference,
    #[serde(default)]
    property_group: Option<SchemaPropertyGroupReference>,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum IdReference {
    String(String),
    Object { id: String },
}

impl IdReference {
    fn id(self) -> Option<String> {
        match self {
            IdReference::String(id) => Some(id),
            IdReference::Object { id } => Some(id),
        }
    }
}

#[derive(Debug, Deserialize)]
struct SchemaPropertyGroupReference {
    id: String,
}

fn detect_local() -> Result<()> {
    let hints = detect_local_languages()?;

    if hints.is_empty() {
        println!("No supported language files detected.");
        println!("Supported local generators: TypeScript, Go, Python");
    } else {
        println!("Detected schema generation hints:");
        for language in hints {
            println!(
                "  - {}: suggested output {}",
                language.display_name(),
                language.default_output_path()
            );
        }
    }

    Ok(())
}

fn language_names(languages: &[LocalLanguage]) -> Vec<&'static str> {
    languages.iter().map(LocalLanguage::display_name).collect()
}

fn detect_local_languages() -> Result<Vec<LocalLanguage>> {
    let cwd = std::env::current_dir().context("Failed to determine current directory")?;
    let mut languages = Vec::new();

    if cwd.join("package.json").exists() || cwd.join("tsconfig.json").exists() {
        languages.push(LocalLanguage::Typescript);
    }
    if cwd.join("go.mod").exists() {
        languages.push(LocalLanguage::Golang);
    }
    if cwd.join("pyproject.toml").exists() || cwd.join("requirements.txt").exists() {
        languages.push(LocalLanguage::Python);
    }

    Ok(languages)
}

fn starter_plan(baseline: Baseline, naming: &str) -> TrackingPlan {
    let mut property_groups = BTreeMap::new();
    property_groups.insert(
        "account_context".to_string(),
        PropertyGroup {
            description: "Shared account-level context.".to_string(),
            properties: BTreeMap::from([
                (
                    "account_id".to_string(),
                    PropertySpec {
                        kind: PropertyKind::String,
                        required: true,
                        description: Some("Stable account identifier.".to_string()),
                    },
                ),
                (
                    "plan".to_string(),
                    PropertySpec {
                        kind: PropertyKind::String,
                        required: false,
                        description: Some("Commercial plan at capture time.".to_string()),
                    },
                ),
            ]),
        },
    );

    let mut events = BTreeMap::new();
    if matches!(
        baseline,
        Baseline::PosthogGrowthV0 | Baseline::Aarrr | Baseline::ActivationRevenue
    ) {
        events.insert(
            "user_signed_up".to_string(),
            EventSpec {
                category: "acquisition".to_string(),
                description: "User completed account creation.".to_string(),
                owner: "growth".to_string(),
                tags: vec!["activation".to_string()],
                property_groups: vec!["account_context".to_string()],
                properties: BTreeMap::from([(
                    "signup_method".to_string(),
                    PropertySpec {
                        kind: PropertyKind::String,
                        required: true,
                        description: Some("Signup method selected by the user.".to_string()),
                    },
                )]),
                primary_property: Some("signup_method".to_string()),
                status: "verified".to_string(),
            },
        );
    }
    if matches!(baseline, Baseline::PosthogGrowthV0) {
        events.insert(
            "core_value_received".to_string(),
            EventSpec {
                category: "north_star".to_string(),
                description: "User performed the core action that represents product value. Rename this to your product-specific North Star event.".to_string(),
                owner: "product".to_string(),
                tags: vec!["north_star".to_string()],
                property_groups: vec!["account_context".to_string()],
                properties: BTreeMap::new(),
                primary_property: None,
                status: "draft".to_string(),
            },
        );
        events.insert(
            "activation_completed".to_string(),
            EventSpec {
                category: "activation".to_string(),
                description: "User reached the first moment of real product value. Rename this to your product-specific activation event or split it into an activation sequence.".to_string(),
                owner: "product".to_string(),
                tags: vec!["activation".to_string()],
                property_groups: vec!["account_context".to_string()],
                properties: BTreeMap::new(),
                primary_property: None,
                status: "draft".to_string(),
            },
        );
        events.insert(
            "retention_action_completed".to_string(),
            EventSpec {
                category: "retention".to_string(),
                description: "User repeated the meaningful behavior that indicates ongoing usage. Rename this to the action you expect retained users to perform again.".to_string(),
                owner: "product".to_string(),
                tags: vec!["retention".to_string()],
                property_groups: vec!["account_context".to_string()],
                properties: BTreeMap::new(),
                primary_property: None,
                status: "draft".to_string(),
            },
        );
    }
    if matches!(
        baseline,
        Baseline::PosthogGrowthV0 | Baseline::Aarrr | Baseline::ActivationRevenue
    ) {
        events.insert(
            "subscription_purchased".to_string(),
            EventSpec {
                category: "revenue".to_string(),
                description: "Customer purchased a subscription or paid plan.".to_string(),
                owner: "growth".to_string(),
                tags: vec!["revenue".to_string()],
                property_groups: vec!["account_context".to_string()],
                properties: BTreeMap::from([
                    (
                        "price".to_string(),
                        PropertySpec {
                            kind: PropertyKind::Numeric,
                            required: true,
                            description: Some("Amount paid as a numeric value.".to_string()),
                        },
                    ),
                    (
                        "currency".to_string(),
                        PropertySpec {
                            kind: PropertyKind::String,
                            required: true,
                            description: Some("ISO 4217 currency code.".to_string()),
                        },
                    ),
                    (
                        "product_id".to_string(),
                        PropertySpec {
                            kind: PropertyKind::String,
                            required: false,
                            description: Some("Stable product identifier.".to_string()),
                        },
                    ),
                    (
                        "subscription_id".to_string(),
                        PropertySpec {
                            kind: PropertyKind::String,
                            required: false,
                            description: Some("Stable subscription identifier.".to_string()),
                        },
                    ),
                ]),
                primary_property: Some("price".to_string()),
                status: if matches!(baseline, Baseline::PosthogGrowthV0) {
                    "draft".to_string()
                } else {
                    "verified".to_string()
                },
            },
        );
    }
    if matches!(baseline, Baseline::PosthogGrowthV0 | Baseline::Aarrr) {
        events.insert(
            "teammate_invited".to_string(),
            EventSpec {
                category: "referral".to_string(),
                description: "User invited another teammate.".to_string(),
                owner: "growth".to_string(),
                tags: vec!["referral".to_string()],
                property_groups: vec!["account_context".to_string()],
                properties: BTreeMap::new(),
                primary_property: None,
                status: "draft".to_string(),
            },
        );
    }

    TrackingPlan {
        version: 1,
        naming: NamingRules {
            event: naming.to_string(),
        },
        baselines: vec![baseline.as_str().to_string()],
        property_groups,
        events,
    }
}

fn read_tracking_plan(source: &str) -> Result<TrackingPlan> {
    let content = fs::read_to_string(source).context(format!("Failed to read {source}"))?;
    serde_yaml::from_str(&content).context(format!("Failed to parse {source}"))
}

fn validate_tracking_plan(plan: &TrackingPlan) -> Result<()> {
    let mut errors = Vec::new();

    if plan.version != 1 {
        errors.push(format!("version must be 1, got {}", plan.version));
    }
    if plan.naming.event != "snake_case_past_tense" {
        errors.push(format!(
            "naming.event must be snake_case_past_tense, got {}",
            plan.naming.event
        ));
    }

    let valid_categories: HashSet<&str> = [
        "north_star",
        "acquisition",
        "activation",
        "retention",
        "revenue",
        "referral",
        "identity",
        "diagnostic",
    ]
    .into_iter()
    .collect();
    let valid_statuses: HashSet<&str> = ["draft", "verified", "deprecated"].into_iter().collect();

    for (name, event) in &plan.events {
        if !is_snake_case(name) {
            errors.push(format!("event `{name}` must use snake_case"));
        }
        if event.description.trim().is_empty() {
            errors.push(format!("event `{name}` is missing description"));
        }
        if event.owner.trim().is_empty() {
            errors.push(format!("event `{name}` is missing owner"));
        }
        if !valid_categories.contains(event.category.as_str()) {
            errors.push(format!(
                "event `{name}` has invalid type `{}`",
                event.category
            ));
        }
        if !valid_statuses.contains(event.status.as_str()) {
            errors.push(format!(
                "event `{name}` has invalid status `{}`",
                event.status
            ));
        }
        for group in &event.property_groups {
            if !plan.property_groups.contains_key(group) {
                errors.push(format!(
                    "event `{name}` references unknown property group `{group}`"
                ));
            }
        }
        for prop_name in event.properties.keys() {
            if !is_snake_case(prop_name) {
                errors.push(format!(
                    "event `{name}` property `{prop_name}` must use snake_case"
                ));
            }
        }
    }

    for (group_name, group) in &plan.property_groups {
        if !is_snake_case(group_name) {
            errors.push(format!("property group `{group_name}` must use snake_case"));
        }
        if group.description.trim().is_empty() {
            errors.push(format!(
                "property group `{group_name}` is missing description"
            ));
        }
        for prop_name in group.properties.keys() {
            if !is_snake_case(prop_name) {
                errors.push(format!(
                    "property group `{group_name}` property `{prop_name}` must use snake_case"
                ));
            }
        }
    }

    if errors.is_empty() {
        Ok(())
    } else {
        Err(anyhow::anyhow!(
            "Tracking plan validation failed:\n- {}",
            errors.join("\n- ")
        ))
    }
}

fn is_snake_case(value: &str) -> bool {
    !value.is_empty()
        && value
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
        && !value.starts_with('_')
        && !value.ends_with('_')
        && !value.contains("__")
}

fn hash_plan(plan: &TrackingPlan) -> Result<String> {
    let stable = serde_yaml::to_string(plan).context("Failed to serialize tracking plan")?;
    let mut hasher = Sha256::new();
    hasher.update(stable.as_bytes());
    Ok(format!("{:x}", hasher.finalize()))
}

fn write_generated_file(plan: &TrackingPlan, lang: LocalLanguage, output_path: &str) -> Result<()> {
    if let Some(parent) = Path::new(output_path).parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .context(format!("Failed to create directory {}", parent.display()))?;
        }
    }

    let content = match lang {
        LocalLanguage::Typescript => generate_typescript(plan),
        LocalLanguage::Golang => generate_go(plan, &go_package_name(output_path)),
        LocalLanguage::Python => generate_python(plan),
    };
    fs::write(output_path, content).context(format!("Failed to write {output_path}"))?;
    Ok(())
}

fn all_event_properties<'a>(
    plan: &'a TrackingPlan,
    event: &'a EventSpec,
) -> BTreeMap<&'a str, &'a PropertySpec> {
    let mut props = BTreeMap::new();
    for group_name in &event.property_groups {
        if let Some(group) = plan.property_groups.get(group_name) {
            for (name, prop) in &group.properties {
                props.insert(name.as_str(), prop);
            }
        }
    }
    for (name, prop) in &event.properties {
        props.insert(name.as_str(), prop);
    }
    props
}

fn generate_typescript(plan: &TrackingPlan) -> String {
    let mut out =
        String::from("// Generated by posthog-cli schema generate. Do not edit by hand.\n\n");
    out.push_str("export type PostHogEventName =\n");
    for name in plan.events.keys() {
        out.push_str(&format!("  | '{}'\n", name));
    }
    out.push_str("\nexport type PostHogEventProperties = {\n");
    for (event_name, event) in &plan.events {
        out.push_str(&format!(
            "  /** {} */\n  '{}': {{\n",
            ts_doc_comment(&event.description),
            event_name
        ));
        for (prop_name, prop) in all_event_properties(plan, event) {
            let optional = if prop.required { "" } else { "?" };
            out.push_str(&format!(
                "    {}{}: {}\n",
                prop_name,
                optional,
                ts_type(&prop.kind)
            ));
        }
        out.push_str("  }\n");
    }
    out.push_str("}\n\n");
    out.push_str("export function captureTyped<E extends PostHogEventName>(posthog: { capture: (event: E, properties: PostHogEventProperties[E]) => void }, event: E, properties: PostHogEventProperties[E]): void {\n");
    out.push_str("  posthog.capture(event, properties)\n}\n");
    out
}

fn ts_doc_comment(value: &str) -> String {
    value
        .replace("*/", "*\\/")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn generate_go(plan: &TrackingPlan, package_name: &str) -> String {
    let mut out = format!(
        "// Generated by posthog-cli schema generate. Do not edit by hand.\npackage {package_name}\n\n",
    );
    out.push_str("type EventName string\n\nconst (\n");
    let max_const_name_len = plan
        .events
        .keys()
        .map(|name| pascal_case(name).len())
        .max()
        .unwrap_or(0);
    for name in plan.events.keys() {
        let const_name = pascal_case(name);
        out.push_str(&format!(
            "\t{}{}EventName = \"{}\"\n",
            const_name,
            spaces(max_const_name_len - const_name.len() + 1),
            name
        ));
    }
    out.push_str(")\n\n");
    for (event_name, event) in &plan.events {
        let event_type = format!("{}Properties", pascal_case(event_name));
        let props = all_event_properties(plan, event);
        out.push_str(&format!("type {} struct {{\n", event_type));
        let go_fields: Vec<(String, String, String)> = props
            .iter()
            .map(|(prop_name, prop)| {
                (
                    pascal_case(prop_name),
                    go_type(&prop.kind, prop.required),
                    format!(
                        "`json:\"{}{}\"`",
                        prop_name,
                        if prop.required { "" } else { ",omitempty" }
                    ),
                )
            })
            .collect();
        let max_field_name_len = go_fields
            .iter()
            .map(|(field_name, _, _)| field_name.len())
            .max()
            .unwrap_or(0);
        let max_field_type_len = go_fields
            .iter()
            .map(|(_, field_type, _)| field_type.len())
            .max()
            .unwrap_or(0);
        for (field_name, field_type, tag) in &go_fields {
            out.push_str(&format!(
                "\t{}{}{}{}{}\n",
                field_name,
                spaces(max_field_name_len - field_name.len() + 1),
                field_type,
                spaces(max_field_type_len - field_type.len() + 1),
                tag
            ));
        }
        out.push_str("}\n\n");
        let required: Vec<(&str, &PropertySpec)> = props
            .iter()
            .filter(|(_, prop)| prop.required)
            .map(|(name, prop)| (*name, *prop))
            .collect();
        let args = required
            .iter()
            .map(|(name, prop)| format!("{} {}", lower_camel_case(name), go_type(&prop.kind, true)))
            .collect::<Vec<_>>()
            .join(", ");
        out.push_str(&format!(
            "func New{}({}) {} {{\n",
            event_type, args, event_type
        ));
        out.push_str(&format!("\treturn {}{{\n", event_type));
        let max_required_field_len = required
            .iter()
            .map(|(name, _)| pascal_case(name).len())
            .max()
            .unwrap_or(0);
        for (name, _) in required {
            let field_name = pascal_case(name);
            out.push_str(&format!(
                "\t\t{}:{}{},\n",
                field_name,
                spaces(max_required_field_len - field_name.len() + 1),
                lower_camel_case(name)
            ));
        }
        out.push_str("\t}\n}\n\n");
    }
    if out.ends_with("\n\n") {
        out.pop();
    }
    out
}

fn go_package_name(output_path: &str) -> String {
    let package_name = Path::new(output_path)
        .parent()
        .and_then(|parent| parent.file_name())
        .and_then(|name| name.to_str())
        .unwrap_or("typed");

    sanitize_go_package_name(package_name)
}

fn sanitize_go_package_name(name: &str) -> String {
    let mut sanitized = String::new();
    for character in name.chars() {
        if character.is_ascii_alphanumeric() || character == '_' {
            sanitized.push(character.to_ascii_lowercase());
        } else if character == '-' || character == ' ' {
            sanitized.push('_');
        }
    }

    let sanitized = sanitized.trim_matches('_');
    if sanitized.is_empty() {
        return "typed".to_string();
    }

    let package_name = if sanitized
        .chars()
        .next()
        .map(|character| character.is_ascii_digit())
        .unwrap_or(false)
    {
        format!("pkg_{sanitized}")
    } else {
        sanitized.to_string()
    };

    if GO_KEYWORDS.contains(&package_name.as_str()) {
        format!("{package_name}_pkg")
    } else {
        package_name
    }
}

const GO_KEYWORDS: &[&str] = &[
    "break",
    "default",
    "func",
    "interface",
    "select",
    "case",
    "defer",
    "go",
    "map",
    "struct",
    "chan",
    "else",
    "goto",
    "package",
    "switch",
    "const",
    "fallthrough",
    "if",
    "range",
    "type",
    "continue",
    "for",
    "import",
    "return",
    "var",
];

fn spaces(count: usize) -> String {
    " ".repeat(count)
}

fn generate_python(plan: &TrackingPlan) -> String {
    let mut out = String::from("# Generated by posthog-cli schema generate. Do not edit by hand.\nfrom __future__ import annotations\n\nfrom dataclasses import dataclass\nfrom typing import Any, Literal\n\n");
    out.push_str("PostHogEventName = Literal[\n");
    for name in plan.events.keys() {
        out.push_str(&format!("    \"{}\",\n", name));
    }
    out.push_str("]\n\n");
    for (event_name, event) in &plan.events {
        out.push_str("@dataclass\n");
        out.push_str(&format!("class {}Properties:\n", pascal_case(event_name)));
        let props = all_event_properties(plan, event);
        if props.is_empty() {
            out.push_str("    pass\n\n");
        } else {
            for (prop_name, prop) in props.iter().filter(|(_, prop)| prop.required) {
                out.push_str(&format!("    {}: {}\n", prop_name, py_type(&prop.kind)));
            }
            for (prop_name, prop) in props.iter().filter(|(_, prop)| !prop.required) {
                out.push_str(&format!(
                    "    {}: {} | None = None\n",
                    prop_name,
                    py_type(&prop.kind)
                ));
            }
            out.push('\n');
        }
    }
    out
}

fn ts_type(kind: &PropertyKind) -> &'static str {
    match kind {
        PropertyKind::String | PropertyKind::DateTime => "string",
        PropertyKind::Numeric => "number",
        PropertyKind::Boolean => "boolean",
        PropertyKind::Object => "Record<string, unknown>",
    }
}

fn go_type(kind: &PropertyKind, required: bool) -> String {
    let base = match kind {
        PropertyKind::String | PropertyKind::DateTime => "string",
        PropertyKind::Numeric => "float64",
        PropertyKind::Boolean => "bool",
        PropertyKind::Object => "map[string]any",
    };
    if required {
        base.to_string()
    } else {
        format!("*{base}")
    }
}

fn py_type(kind: &PropertyKind) -> &'static str {
    match kind {
        PropertyKind::String | PropertyKind::DateTime => "str",
        PropertyKind::Numeric => "float",
        PropertyKind::Boolean => "bool",
        PropertyKind::Object => "dict[str, Any]",
    }
}

fn pascal_case(value: &str) -> String {
    value
        .split('_')
        .filter(|part| !part.is_empty())
        .map(|part| {
            let mut chars = part.chars();
            match chars.next() {
                Some(first) => first.to_ascii_uppercase().to_string() + chars.as_str(),
                None => String::new(),
            }
        })
        .collect()
}

fn lower_camel_case(value: &str) -> String {
    let pascal = pascal_case(value);
    let mut chars = pascal.chars();
    match chars.next() {
        Some(first) => first.to_ascii_lowercase().to_string() + chars.as_str(),
        None => String::new(),
    }
}

#[cfg(test)]
mod local_schema_tests {
    use super::*;

    #[test]
    fn validates_aarrr_starter_plan() {
        let plan = starter_plan(Baseline::Aarrr, "snake_case_past_tense");

        validate_tracking_plan(&plan).expect("starter plan should validate");

        assert_eq!(plan.events.len(), 3);
        assert!(plan.events.contains_key("user_signed_up"));
        assert!(plan.events.contains_key("subscription_purchased"));
        assert!(plan.events.contains_key("teammate_invited"));
    }

    #[test]
    fn validates_posthog_growth_v0_starter_plan() {
        let plan = starter_plan(Baseline::PosthogGrowthV0, "snake_case_past_tense");

        validate_tracking_plan(&plan).expect("starter plan should validate");

        assert_eq!(plan.events.len(), 6);
        assert!(plan.events.contains_key("user_signed_up"));
        assert!(plan.events.contains_key("core_value_received"));
        assert!(plan.events.contains_key("activation_completed"));
        assert!(plan.events.contains_key("retention_action_completed"));
        assert!(plan.events.contains_key("subscription_purchased"));
        assert!(plan.events.contains_key("teammate_invited"));
    }

    #[test]
    fn rejects_unknown_property_group() {
        let mut plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        plan.events
            .get_mut("user_signed_up")
            .unwrap()
            .property_groups
            .push("missing_context".to_string());

        let error = validate_tracking_plan(&plan).unwrap_err().to_string();

        assert!(error.contains("unknown property group `missing_context`"));
    }

    #[test]
    fn generates_typescript_go_and_python() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");

        let ts = generate_typescript(&plan);
        assert!(ts.contains("export type PostHogEventName"));
        assert!(ts.contains("'user_signed_up'"));
        assert!(ts.contains("signup_method: string"));

        let go = generate_go(&plan, "analytics");
        assert!(go.contains("package analytics"));
        assert!(go.contains("UserSignedUp"));
        assert!(go.contains("EventName = \"user_signed_up\""));
        assert!(go.contains("SignupMethod string"));

        let py = generate_python(&plan);
        assert!(py.contains("PostHogEventName = Literal"));
        assert!(py.contains("class UserSignedUpProperties"));
        assert!(py.contains("signup_method: str"));
    }

    #[test]
    fn escapes_typescript_doc_comments() {
        let mut plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        plan.events.get_mut("user_signed_up").unwrap().description =
            "Safe text */\nexport const injected = true\n/**".to_string();

        let ts = generate_typescript(&plan);

        assert!(ts.contains("Safe text *\\/ export const injected = true /**"));
        assert!(!ts.contains("*/\nexport const injected"));
    }

    #[test]
    fn derives_go_package_from_output_path() {
        assert_eq!(go_package_name("posthog-events-typed.go"), "typed");
        assert_eq!(go_package_name("internal/analytics/events.go"), "analytics");
        assert_eq!(
            go_package_name("internal/posthog-events/events.go"),
            "posthog_events"
        );
        assert_eq!(go_package_name("internal/123/events.go"), "pkg_123");
        assert_eq!(go_package_name("internal/type/events.go"), "type_pkg");
    }

    #[test]
    fn remote_plan_maps_event_properties_to_event_specific_groups() {
        let plan = starter_plan(Baseline::PosthogGrowthV0, "snake_case_past_tense");

        let remote_plan = build_remote_plan(&plan).expect("remote plan should build");

        assert!(remote_plan.property_groups.contains_key("account_context"));
        assert!(remote_plan
            .property_groups
            .contains_key("user_signed_up_properties"));
        assert!(remote_plan
            .property_groups
            .contains_key("subscription_purchased_properties"));
        assert!(remote_plan
            .event_schema_links
            .contains(&("user_signed_up".to_string(), "account_context".to_string())));
        assert!(remote_plan.event_schema_links.contains(&(
            "user_signed_up".to_string(),
            "user_signed_up_properties".to_string()
        )));
    }

    #[test]
    fn remote_plan_preserves_event_metadata() {
        let plan = starter_plan(Baseline::PosthogGrowthV0, "snake_case_past_tense");

        let remote_plan = build_remote_plan(&plan).expect("remote plan should build");
        let event = remote_plan
            .events
            .get("user_signed_up")
            .expect("event should exist");

        assert_eq!(event.name, "user_signed_up");
        assert_eq!(event.description, "User completed account creation.");
        assert_eq!(event.tags, vec!["activation"]);
        assert_eq!(event.primary_property.as_deref(), Some("signup_method"));
        assert_eq!(event.status, "verified");
    }

    #[test]
    fn remote_payloads_preserve_event_and_property_group_fields() {
        let plan = starter_plan(Baseline::PosthogGrowthV0, "snake_case_past_tense");
        let remote_plan = build_remote_plan(&plan).expect("remote plan should build");

        let event_payload = event_definition_payload(
            remote_plan
                .events
                .get("user_signed_up")
                .expect("event should exist"),
        );
        assert_eq!(event_payload["name"].as_str(), Some("user_signed_up"));
        assert_eq!(
            event_payload["description"].as_str(),
            Some("User completed account creation.")
        );
        assert_eq!(event_payload["tags"][0].as_str(), Some("activation"));
        assert_eq!(
            event_payload["primary_property"].as_str(),
            Some("signup_method")
        );
        assert_eq!(event_payload["verified"].as_bool(), Some(true));
        assert_eq!(event_payload["hidden"].as_bool(), Some(false));

        let draft_event = DesiredEvent {
            name: "draft_event".to_string(),
            description: "Draft event.".to_string(),
            tags: vec!["draft".to_string()],
            primary_property: None,
            status: "draft".to_string(),
        };
        let draft_payload = event_definition_payload(&draft_event);
        assert_eq!(draft_payload["verified"].as_bool(), Some(false));
        assert_eq!(draft_payload["hidden"].as_bool(), Some(false));

        let deprecated_event = DesiredEvent {
            status: "deprecated".to_string(),
            ..draft_event
        };
        let deprecated_payload = event_definition_payload(&deprecated_event);
        assert_eq!(deprecated_payload["verified"].as_bool(), Some(false));
        assert_eq!(deprecated_payload["hidden"].as_bool(), Some(true));

        let property_group_payload = property_group_payload(
            remote_plan
                .property_groups
                .get("account_context")
                .expect("property group should exist"),
        );
        assert_eq!(
            property_group_payload["name"].as_str(),
            Some("account_context")
        );
        assert_eq!(
            property_group_payload["description"].as_str(),
            Some("Shared account-level context.")
        );
        assert_eq!(
            property_group_payload["properties"][0]["name"].as_str(),
            Some("account_id")
        );
        assert_eq!(
            property_group_payload["properties"][0]["property_type"].as_str(),
            Some("String")
        );
        assert_eq!(
            property_group_payload["properties"][0]["is_required"].as_bool(),
            Some(true)
        );
        assert_eq!(
            property_group_payload["properties"][0]["description"].as_str(),
            Some("Stable account identifier.")
        );
    }

    #[test]
    fn remote_diff_reports_create_operations_for_empty_remote_state() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");
        let remote = RemoteState {
            events: BTreeMap::new(),
            property_groups: BTreeMap::new(),
            event_schema_links: BTreeMap::new(),
        };

        let changes = diff_remote_state(&desired, &remote);

        assert!(changes.contains(&SyncChange::CreateEvent("user_signed_up".to_string())));
        assert!(changes.contains(&SyncChange::CreatePropertyGroup(
            "account_context".to_string()
        )));
        assert!(changes.contains(&SyncChange::AttachEventSchema {
            event: "user_signed_up".to_string(),
            property_group: "user_signed_up_properties".to_string(),
        }));
    }

    #[test]
    fn remote_diff_reports_no_drift_when_remote_matches_desired_state() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");
        let remote = remote_state_from_desired(&desired);

        let changes = diff_remote_state(&desired, &remote);

        assert!(changes.is_empty());
    }

    #[test]
    fn remote_diff_reports_event_updates() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");
        let mut remote = remote_state_from_desired(&desired);
        remote
            .events
            .get_mut("user_signed_up")
            .expect("remote event should exist")
            .description = Some("Edited remotely".to_string());

        let changes = diff_remote_state(&desired, &remote);

        assert_eq!(
            changes,
            vec![SyncChange::UpdateEvent("user_signed_up".to_string())]
        );
    }

    #[test]
    fn remote_diff_reports_missing_event_description() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");
        let mut remote = remote_state_from_desired(&desired);
        remote
            .events
            .get_mut("user_signed_up")
            .expect("remote event should exist")
            .description = None;

        let changes = diff_remote_state(&desired, &remote);

        assert_eq!(
            changes,
            vec![SyncChange::UpdateEvent("user_signed_up".to_string())]
        );
    }

    #[test]
    fn remote_diff_reports_event_metadata_updates() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");

        let mut remote_with_tags = remote_state_from_desired(&desired);
        remote_with_tags
            .events
            .get_mut("user_signed_up")
            .expect("remote event should exist")
            .tags = vec!["edited".to_string()];
        assert_eq!(
            diff_remote_state(&desired, &remote_with_tags),
            vec![SyncChange::UpdateEvent("user_signed_up".to_string())]
        );

        let mut remote_with_primary_property = remote_state_from_desired(&desired);
        remote_with_primary_property
            .events
            .get_mut("user_signed_up")
            .expect("remote event should exist")
            .primary_property = Some("account_id".to_string());
        assert_eq!(
            diff_remote_state(&desired, &remote_with_primary_property),
            vec![SyncChange::UpdateEvent("user_signed_up".to_string())]
        );

        let mut remote_with_status = remote_state_from_desired(&desired);
        remote_with_status
            .events
            .get_mut("user_signed_up")
            .expect("remote event should exist")
            .status = "draft".to_string();
        assert_eq!(
            diff_remote_state(&desired, &remote_with_status),
            vec![SyncChange::UpdateEvent("user_signed_up".to_string())]
        );
    }

    #[test]
    fn remote_diff_reports_property_group_updates() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");
        let mut remote = remote_state_from_desired(&desired);
        remote
            .property_groups
            .get_mut("account_context")
            .expect("remote property group should exist")
            .properties
            .get_mut("account_id")
            .expect("remote property should exist")
            .description = "Edited remotely".to_string();

        let changes = diff_remote_state(&desired, &remote);

        assert_eq!(
            changes,
            vec![SyncChange::UpdatePropertyGroup(
                "account_context".to_string()
            )]
        );
    }

    #[test]
    fn remote_diff_reports_property_group_description_updates() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");
        let mut remote = remote_state_from_desired(&desired);
        remote
            .property_groups
            .get_mut("account_context")
            .expect("remote property group should exist")
            .description = "Edited remotely".to_string();

        let changes = diff_remote_state(&desired, &remote);

        assert_eq!(
            changes,
            vec![SyncChange::UpdatePropertyGroup(
                "account_context".to_string()
            )]
        );
    }

    #[test]
    fn remote_diff_reports_missing_event_schema_links() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");
        let mut remote = remote_state_from_desired(&desired);
        remote.event_schema_links.remove(&(
            "user_signed_up".to_string(),
            "user_signed_up_properties".to_string(),
        ));

        let changes = diff_remote_state(&desired, &remote);

        assert_eq!(
            changes,
            vec![SyncChange::AttachEventSchema {
                event: "user_signed_up".to_string(),
                property_group: "user_signed_up_properties".to_string(),
            }]
        );
    }

    #[test]
    fn remote_diff_reports_unexpected_event_schema_links_on_managed_events() {
        let plan = starter_plan(Baseline::ActivationRevenue, "snake_case_past_tense");
        let desired = build_remote_plan(&plan).expect("remote plan should build");
        let mut remote = remote_state_from_desired(&desired);
        remote.event_schema_links.insert(
            ("user_signed_up".to_string(), "extra_context".to_string()),
            "schema-extra".to_string(),
        );
        remote.event_schema_links.insert(
            ("unmanaged_event".to_string(), "extra_context".to_string()),
            "schema-unmanaged".to_string(),
        );

        let changes = diff_remote_state(&desired, &remote);

        assert_eq!(
            changes,
            vec![SyncChange::UnexpectedEventSchema {
                event: "user_signed_up".to_string(),
                property_group: "extra_context".to_string(),
            }]
        );
    }

    fn remote_state_from_desired(desired: &DesiredRemotePlan) -> RemoteState {
        RemoteState {
            events: desired
                .events
                .iter()
                .enumerate()
                .map(|(index, (name, event))| {
                    (
                        name.clone(),
                        RemoteEvent {
                            id: format!("event-{index}"),
                            name: event.name.clone(),
                            description: Some(event.description.clone()),
                            tags: event.tags.clone(),
                            primary_property: event.primary_property.clone(),
                            status: event.status.clone(),
                        },
                    )
                })
                .collect(),
            property_groups: desired
                .property_groups
                .iter()
                .enumerate()
                .map(|(index, (name, group))| {
                    (
                        name.clone(),
                        RemotePropertyGroup {
                            id: format!("group-{index}"),
                            name: group.name.clone(),
                            description: group.description.clone(),
                            properties: group.properties.clone(),
                        },
                    )
                })
                .collect(),
            event_schema_links: desired
                .event_schema_links
                .iter()
                .enumerate()
                .map(|(index, link)| (link.clone(), format!("schema-{index}")))
                .collect(),
        }
    }
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
