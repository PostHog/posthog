//! `agents` — deploy + sync code-level PostHog agents.
//!
//! An agent *bundle* is a directory holding `spec.json` + `agent.md` (+ optional
//! `skills/<id>/SKILL.md` and `tests/*.json`). `deploy` runs each bundle through
//! the authoring API (create application → branch/create draft → push bundle →
//! patch spec → validate → freeze → promote); `pull` syncs a live agent back to
//! disk; `list` shows discoverable bundles.
//!
//! Auth + the project-scoped API client come from the shared invocation context
//! (`posthog login` / `POSTHOG_CLI_*`), same as every other command. Experimental:
//! gated behind the top-level `--experimental` flag.

mod deploy;
mod list;
mod pull;

use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result};
use clap::{Args, Subcommand};
use colored::Colorize;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use walkdir::WalkDir;

use crate::invocation_context::context;

pub use deploy::deploy_agents;
pub use list::list_agents;
pub use pull::pull_agents;

// ── debug logging (mirrors exp endpoints) ───────────────────────────────────

#[inline]
pub(crate) fn debug_request(debug: bool, method: &str, path: &str) {
    if debug {
        eprintln!("  {} {} {}", "DEBUG".cyan().bold(), method, path);
    }
}

#[inline]
pub(crate) fn debug_error<E: std::fmt::Display>(debug: bool, error: &E) {
    if debug {
        eprintln!("  {} {}", "Error:".red(), error);
    }
}

// ── platform reads (shared by deploy + pull) ─────────────────────────────────

/// GET a project-scoped path and parse the JSON body. Non-2xx is already an Err.
pub(crate) fn get_json(path: &str, debug: bool) -> Result<Value> {
    let client = &context().client;
    debug_request(debug, "GET", path);
    let resp = client
        .send_get(client.project_url(path)?, |req| req)
        .inspect_err(|e| debug_error(debug, e))?;
    resp.json()
        .with_context(|| format!("parsing response for {path}"))
}

/// The application id whose slug matches, or None if no such application exists.
pub(crate) fn find_application(slug: &str, debug: bool) -> Result<Option<String>> {
    let payload = get_json("agent_applications/", debug).context("listing applications")?;
    let Some(results) = payload.get("results").and_then(Value::as_array) else {
        return Ok(None);
    };
    Ok(results
        .iter()
        .find(|a| a.get("slug").and_then(Value::as_str) == Some(slug))
        .and_then(|a| a.get("id").and_then(Value::as_str))
        .map(str::to_string))
}

/// A revision's typed bundle: `{ agent_md, skills:[{id,body}], tools:[{id,source}], spec }`.
pub(crate) fn get_typed_bundle(app_id: &str, rev_id: &str, debug: bool) -> Result<Value> {
    let payload = get_json(
        &format!("agent_applications/{app_id}/revisions/{rev_id}/bundle/"),
        debug,
    )
    .with_context(|| format!("read bundle for {rev_id}"))?;
    payload
        .get("bundle")
        .filter(|b| b.is_object())
        .cloned()
        .with_context(|| format!("bundle read returned no bundle for {rev_id}"))
}

// ── command surface ──────────────────────────────────────────────────────────

#[derive(Subcommand)]
pub enum AgentsCommand {
    /// Deploy bundle(s) to PostHog: create → validate → freeze → promote
    Deploy(DeployArgs),

    /// Pull a live agent's bundle (prompt, skills, custom tools) back to disk
    Pull(PullArgs),

    /// List discoverable agent bundles in a directory
    List(ListArgs),
}

#[derive(Args, Clone)]
pub struct DeployArgs {
    /// Directory of agent bundles (each a subdir with spec.json + agent.md).
    pub dir: String,

    /// Only deploy bundles whose slug equals or contains one of these.
    pub names: Vec<String>,

    /// Preview the plan without mutating anything.
    #[arg(long)]
    pub dry_run: bool,

    /// Skip the confirmation prompt.
    #[arg(long, short = 'y')]
    pub yes: bool,

    /// Set obviously-fake placeholders for required secrets so secret-gated
    /// agents can promote (local dev — the agents won't actually function).
    #[arg(long)]
    pub dummy_secrets: bool,

    /// Override every declarative trigger's auth modes (e.g. `public`, `posthog`).
    #[arg(long)]
    pub auth_mode: Option<String>,

    /// Rewrite every `mcps[].url` (local-dev / cross-region).
    #[arg(long)]
    pub mcp_url: Option<String>,

    /// Show a line-level diff (agent.md, skills, spec) for each updated bundle
    /// in the plan. Pairs well with `--dry-run`.
    #[arg(long)]
    pub diff: bool,

    /// Show API request/response detail.
    #[arg(long)]
    pub debug: bool,
}

#[derive(Args, Clone)]
pub struct PullArgs {
    /// Directory of agent bundles to pull into.
    pub dir: String,

    /// Only pull bundles whose slug equals or contains one of these.
    pub names: Vec<String>,

    /// Pull the newest revision even if it isn't promoted to live.
    #[arg(long)]
    pub latest: bool,

    /// Also rewrite spec.json (the frozen/normalised spec).
    #[arg(long)]
    pub spec: bool,

    /// Delete on-disk skills/tools the platform no longer has.
    #[arg(long)]
    pub prune: bool,

    /// Preview without writing.
    #[arg(long)]
    pub dry_run: bool,

    /// Show API request/response detail.
    #[arg(long)]
    pub debug: bool,
}

#[derive(Args, Clone)]
pub struct ListArgs {
    /// Directory of agent bundles.
    pub dir: String,
}

impl AgentsCommand {
    pub fn run(&self) -> Result<()> {
        match self {
            AgentsCommand::Deploy(args) => deploy_agents(args),
            AgentsCommand::Pull(args) => pull_agents(args),
            AgentsCommand::List(args) => list_agents(args),
        }
    }
}

// ── bundle loading ───────────────────────────────────────────────────────────

pub struct LoadedBundle {
    pub slug: String,
    pub root: PathBuf,
    pub spec: Value,
    /// Bundle-relative path → content (agent.md, skills/<id>/SKILL.md, tests/*.json).
    pub files: HashMap<String, String>,
}

/// Every immediate subdir of `dir` that holds a deployable bundle (spec.json +
/// agent.md), sorted by slug.
pub fn discover_bundles(dir: &Path) -> Result<Vec<PathBuf>> {
    if !dir.is_dir() {
        anyhow::bail!("not a directory: {}", dir.display());
    }
    let mut out: Vec<PathBuf> = std::fs::read_dir(dir)
        .with_context(|| format!("reading {}", dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_dir() && p.join("spec.json").is_file() && p.join("agent.md").is_file())
        .collect();
    out.sort();
    Ok(out)
}

/// Filter bundle dirs by selector — a selector matches a bundle whose slug
/// equals it or contains it. No selectors → all. Errors on an unknown selector.
pub fn select_bundles(bundles: &[PathBuf], selectors: &[String]) -> Result<Vec<PathBuf>> {
    if selectors.is_empty() {
        return Ok(bundles.to_vec());
    }
    let mut chosen: Vec<PathBuf> = Vec::new();
    for sel in selectors {
        let matches: Vec<&PathBuf> = bundles
            .iter()
            .filter(|b| {
                slug_of(b)
                    .map(|s| s == *sel || s.contains(sel))
                    .unwrap_or(false)
            })
            .collect();
        if matches.is_empty() {
            let known: Vec<String> = bundles.iter().filter_map(|b| slug_of(b)).collect();
            anyhow::bail!(
                "no bundle matches selector \"{sel}\"; known: {}",
                known.join(", ")
            );
        }
        for m in matches {
            if !chosen.contains(m) {
                chosen.push(m.clone());
            }
        }
    }
    Ok(chosen)
}

pub fn slug_of(root: &Path) -> Option<String> {
    root.file_name().map(|n| n.to_string_lossy().to_string())
}

/// Load a bundle dir: spec.json + agent.md + skills/**.md + tests/*.json.
pub fn load_bundle(root: &Path) -> Result<LoadedBundle> {
    let slug = slug_of(root).context("bundle has no directory name")?;
    let spec: Value = serde_json::from_str(
        &std::fs::read_to_string(root.join("spec.json"))
            .with_context(|| format!("reading spec.json for {slug}"))?,
    )
    .with_context(|| format!("parsing spec.json for {slug}"))?;

    let mut files: HashMap<String, String> = HashMap::new();
    files.insert(
        "agent.md".to_string(),
        std::fs::read_to_string(root.join("agent.md"))
            .with_context(|| format!("reading agent.md for {slug}"))?,
    );

    let skills_dir = root.join("skills");
    if skills_dir.is_dir() {
        for entry in WalkDir::new(&skills_dir).sort_by_file_name() {
            let entry = entry?;
            let p = entry.path();
            if p.is_file() && p.extension().is_some_and(|e| e == "md") {
                let rel = p.strip_prefix(root)?.to_string_lossy().replace('\\', "/");
                files.insert(rel, std::fs::read_to_string(p)?);
            }
        }
    }
    let tests_dir = root.join("tests");
    if tests_dir.is_dir() {
        let mut names: Vec<PathBuf> = std::fs::read_dir(&tests_dir)?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.is_file() && p.extension().is_some_and(|e| e == "json"))
            .collect();
        names.sort();
        for p in names {
            let name = p.file_name().unwrap().to_string_lossy();
            files.insert(format!("tests/{name}"), std::fs::read_to_string(&p)?);
        }
    }
    Ok(LoadedBundle {
        slug,
        root: root.to_path_buf(),
        spec,
        files,
    })
}

/// Shape for `PUT /bundle/`: `{ agent_md, skills:[{id,description,body}], tools:[], spec }`.
/// The spec slice drops `skills`/`tools` (server-derived at freeze).
pub fn build_typed_bundle(b: &LoadedBundle, spec: &Value) -> Value {
    let mut skills: Vec<Value> = Vec::new();
    if let Some(arr) = spec.get("skills").and_then(Value::as_array) {
        for r in arr {
            let Some(id) = r.get("id").and_then(Value::as_str) else {
                continue;
            };
            let path = r
                .get("path")
                .and_then(Value::as_str)
                .map(str::to_string)
                .unwrap_or_else(|| format!("skills/{id}.md"));
            skills.push(json!({
                "id": id,
                "description": r.get("description").and_then(Value::as_str).unwrap_or(""),
                "body": b.files.get(&path).cloned().unwrap_or_default(),
            }));
        }
    }
    let mut author_spec = Map::new();
    if let Some(obj) = spec.as_object() {
        for (k, v) in obj {
            if k != "skills" && k != "tools" {
                author_spec.insert(k.clone(), v.clone());
            }
        }
    }
    json!({
        "agent_md": b.files.get("agent.md").cloned().unwrap_or_default(),
        "skills": skills,
        "tools": [],
        "spec": Value::Object(author_spec),
    })
}

/// Per-file sha256 (hex), mirroring the janitor manifest — for idempotency diffs.
pub fn per_file_sha256(files: &HashMap<String, String>) -> HashMap<String, String> {
    files
        .iter()
        .map(|(p, c)| {
            let mut h = Sha256::new();
            h.update(c.as_bytes());
            (p.clone(), format!("{:x}", h.finalize()))
        })
        .collect()
}

// ── spec overrides (local-dev / cross-region) ────────────────────────────────

const DECLARATIVE_TRIGGERS: [&str; 3] = ["webhook", "chat", "mcp"];

/// The PostHog MCP URL matching the target host (local → local MCP, us/eu → their
/// region MCP, else the region-agnostic host).
pub fn posthog_mcp_url_for_host(host: &str) -> String {
    let host = host.to_lowercase();
    if host.contains("localhost") || host.contains("127.0.0.1") {
        "http://localhost:8787/mcp".to_string()
    } else if host.contains("eu.posthog.com") {
        "https://mcp.eu.posthog.com/mcp".to_string()
    } else if host.contains("us.posthog.com") || host.contains("app.posthog.com") {
        "https://mcp.us.posthog.com/mcp".to_string()
    } else {
        "https://mcp.posthog.com/mcp".to_string()
    }
}

/// Apply local-dev overrides to a clone of the spec: per-trigger auth modes and
/// MCP URL rewrites. Production deploys pass no overrides (the spec is untouched
/// except the region MCP rewrite for `posthog`-authed MCPs).
pub fn apply_spec_overrides(
    raw: &Value,
    host: &str,
    auth_mode: Option<&str>,
    mcp_url: Option<&str>,
) -> Result<Value> {
    let mut spec = raw.clone();

    let auth_override: Option<Value> = match auth_mode {
        None => None,
        Some("shared_secret") => {
            anyhow::bail!(
                "--auth-mode shared_secret needs a header/secret_ref; use the bundle's modes"
            )
        }
        Some("public") => {
            Some(json!({ "modes": [{ "type": "public", "acknowledge_public_exposure": true }] }))
        }
        Some(other) => Some(json!({ "modes": [{ "type": other }] })),
    };
    if let Some(triggers) = spec.get_mut("triggers").and_then(Value::as_array_mut) {
        for t in triggers.iter_mut() {
            let is_declarative = t
                .get("type")
                .and_then(Value::as_str)
                .is_some_and(|ty| DECLARATIVE_TRIGGERS.contains(&ty));
            let Some(obj) = t.as_object_mut() else {
                continue;
            };
            if is_declarative {
                if let Some(o) = &auth_override {
                    obj.insert("auth".to_string(), o.clone());
                } else if !obj.contains_key("auth") {
                    obj.insert(
                        "auth".to_string(),
                        json!({ "modes": [{ "type": "posthog_internal" }] }),
                    );
                }
            } else {
                obj.remove("auth");
            }
        }
    }

    let region_mcp = posthog_mcp_url_for_host(host);
    if let Some(mcps) = spec.get_mut("mcps").and_then(Value::as_array_mut) {
        for m in mcps.iter_mut() {
            let provider_is_posthog = m
                .get("auth")
                .and_then(|a| a.get("provider"))
                .and_then(Value::as_str)
                == Some("posthog");
            let Some(obj) = m.as_object_mut() else {
                continue;
            };
            if let Some(url) = mcp_url {
                obj.insert("url".to_string(), json!(url));
            } else if provider_is_posthog {
                obj.insert("url".to_string(), json!(region_mcp));
            }
        }
    }
    Ok(spec)
}
