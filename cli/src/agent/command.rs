//! Agent-first API access. Two surfaces over the same manifest interpreter:
//!   - per-category commands: `posthog-cli <category> <verb> [--flags] [--json '{...}']`
//!     (built dynamically from the manifest and merged into the top-level CLI)
//!   - `posthog-cli exp agent list|run` — the raw, namespaced interface.

use anyhow::{Context, Result};
use clap::{Arg, ArgAction, ArgMatches, Command, Subcommand};
use reqwest::Method;
use serde_json::{Map, Value};

use crate::agent::interpreter::build_request;
use crate::agent::manifest::{load_manifest, Manifest, Param, Tool};
use crate::invocation_context::context;

// ---------------------------------------------------------------------------
// Per-category dynamic commands
// ---------------------------------------------------------------------------

/// All params across path/query/body, in a stable order.
fn all_params(tool: &Tool) -> impl Iterator<Item = &Param> {
    tool.params
        .path
        .iter()
        .chain(tool.params.query.iter())
        .chain(tool.params.body.iter())
}

/// True if `name` is a generated category (a top-level group like `feature-flag`).
pub fn is_category(manifest: &Manifest, name: &str) -> bool {
    manifest.tools.values().any(|t| t.category == name)
}

/// clap's `Str` requires `'static`; the command tree is built once per (short-lived) process,
/// so leaking the dynamically-derived names is the idiomatic way to satisfy that bound.
fn leak(s: &str) -> &'static str {
    Box::leak(s.to_owned().into_boxed_str())
}

/// Add a subcommand per category (e.g. `feature-flag`) with a sub-subcommand per verb
/// (e.g. `create`), exposing scalar params as `--flags` plus a `--json` escape hatch.
pub fn augment_with_categories(mut cmd: Command, manifest: &Manifest) -> Command {
    let existing: std::collections::HashSet<String> =
        cmd.get_subcommands().map(|s| s.get_name().to_string()).collect();

    let mut by_category: std::collections::BTreeMap<&str, Vec<&Tool>> = std::collections::BTreeMap::new();
    for tool in manifest.tools.values() {
        by_category.entry(tool.category.as_str()).or_default().push(tool);
    }

    for (category, tools) in by_category {
        // Never shadow a hand-written top-level command (login, sourcemap, exp, ...).
        if existing.contains(category) {
            continue;
        }
        let mut cat_cmd = Command::new(leak(category))
            .about(format!("{category} commands"))
            .subcommand_required(true)
            .arg_required_else_help(true);

        for tool in tools {
            let mut verb_cmd = Command::new(leak(&tool.verb))
                .about(format!("{} {}", tool.method, tool.path))
                .long_about(format!("{} {}\nMCP tool: {}", tool.method, tool.path, tool.mcp_name));

            for p in all_params(tool) {
                if p.flag_eligible {
                    let value_name = if p.ty.is_empty() { "VALUE".to_string() } else { p.ty.to_uppercase() };
                    verb_cmd = verb_cmd.arg(
                        Arg::new(leak(&p.name))
                            .long(leak(&p.name))
                            .value_name(leak(&value_name)),
                    );
                }
            }
            verb_cmd = verb_cmd
                .arg(
                    Arg::new("json")
                        .long("json")
                        .value_name("JSON")
                        .help("Additional arguments as a JSON object (merged; explicit flags win)"),
                )
                .arg(
                    Arg::new("dry-run")
                        .long("dry-run")
                        .action(ArgAction::SetTrue)
                        .help("Print the resolved request instead of sending it"),
                );
            cat_cmd = cat_cmd.subcommand(verb_cmd);
        }
        cmd = cmd.subcommand(cat_cmd);
    }
    cmd
}

/// Run a per-category invocation. `context()` must already be initialized.
pub fn dispatch_category(manifest: &Manifest, category: &str, cat_matches: &ArgMatches) -> Result<()> {
    let (verb, verb_matches) = cat_matches
        .subcommand()
        .ok_or_else(|| anyhow::anyhow!("Expected a subcommand under `{category}`"))?;

    let tool = manifest
        .tools
        .values()
        .find(|t| t.category == category && t.verb == verb)
        .ok_or_else(|| anyhow::anyhow!("Unknown command: {category} {verb}"))?;

    let mut params = Map::new();

    // Start from --json, then let explicit flags override individual keys.
    if let Some(json) = verb_matches.get_one::<String>("json") {
        match serde_json::from_str::<Value>(json).context("--json must be valid JSON")? {
            Value::Object(obj) => params.extend(obj),
            _ => anyhow::bail!("--json must be a JSON object"),
        }
    }
    for p in all_params(tool) {
        if p.flag_eligible {
            if let Some(raw) = verb_matches.get_one::<String>(&p.name) {
                let ty = if p.ty.is_empty() { None } else { Some(p.ty.as_str()) };
                params.insert(p.name.clone(), flag_value_to_json(raw, ty));
            }
        }
    }

    let dry_run = verb_matches.get_flag("dry-run");
    execute_tool(tool, Value::Object(params), dry_run)
}

/// Coerce a flag's string value to JSON using the param's declared type.
fn flag_value_to_json(raw: &str, ty: Option<&str>) -> Value {
    match ty {
        Some("boolean") => match raw {
            "true" => Value::Bool(true),
            "false" => Value::Bool(false),
            _ => Value::String(raw.to_string()),
        },
        Some("integer") | Some("number") => raw
            .parse::<i64>()
            .map(|n| Value::Number(n.into()))
            .ok()
            .or_else(|| serde_json::Number::from_f64(raw.parse::<f64>().ok()?).map(Value::Number))
            .unwrap_or_else(|| Value::String(raw.to_string())),
        _ => Value::String(raw.to_string()),
    }
}

// ---------------------------------------------------------------------------
// Shared execution
// ---------------------------------------------------------------------------

/// Build the request from the manifest and either print it (dry-run) or send it.
fn execute_tool(tool: &Tool, params: Value, dry_run: bool) -> Result<()> {
    let project_id = context().config.env_id.clone();
    let request = build_request(tool, &params, &project_id)?;

    if dry_run {
        println!("{}", serde_json::to_string_pretty(&request.to_preview())?);
        return Ok(());
    }

    let host = &context().config.host;
    let mut url = reqwest::Url::parse(host).with_context(|| format!("Invalid host: {host}"))?;
    url.set_path(&request.path);
    {
        let mut pairs = url.query_pairs_mut();
        for (k, v) in &request.query {
            pairs.append_pair(k, v);
        }
    }

    let method =
        Method::from_bytes(request.method.as_bytes()).with_context(|| format!("Invalid HTTP method: {}", request.method))?;

    let body = request.body.clone();
    let response = context()
        .client
        .send_request(method, url, move |rb| match &body {
            Some(b) => rb.json(b),
            None => rb,
        })?;

    let text = response.text().context("Failed to read response body")?;
    println!("{text}");
    Ok(())
}

// ---------------------------------------------------------------------------
// Raw `exp agent` interface
// ---------------------------------------------------------------------------

#[derive(Subcommand)]
pub enum AgentCommand {
    /// List available API tools (from the embedded manifest).
    List,
    /// Execute an API tool by its raw name. Pass arguments as a JSON object via --json.
    Run {
        /// Tool name, e.g. `create-feature-flag` or `query-trends`.
        tool: String,
        /// JSON object of arguments.
        #[arg(long, default_value = "{}")]
        json: String,
        /// Print the resolved request instead of sending it.
        #[arg(long, default_value = "false")]
        dry_run: bool,
    },
}

impl AgentCommand {
    pub fn run(&self) -> Result<()> {
        let manifest = load_manifest()?;

        match self {
            AgentCommand::List => {
                for (name, tool) in &manifest.tools {
                    let flag = if tool.annotations.read_only { "ro" } else { "rw" };
                    println!("{}\t{} {}\t[{flag}]\t{} {}", tool.category, tool.verb, name, tool.method, tool.path);
                }
                Ok(())
            }
            AgentCommand::Run { tool, json, dry_run } => {
                let tool_def = manifest
                    .tools
                    .get(tool)
                    .ok_or_else(|| anyhow::anyhow!("Unknown tool: {tool}"))?;
                let params: Value = serde_json::from_str(json).context("--json must be a valid JSON object")?;
                execute_tool(tool_def, params, *dry_run)
            }
        }
    }
}
