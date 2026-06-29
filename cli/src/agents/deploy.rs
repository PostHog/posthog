use std::collections::HashMap;
use std::path::Path;

use anyhow::{Context, Result};
use colored::Colorize;
use inquire::Confirm;
use serde_json::{json, Value};

use crate::invocation_context::context;

use super::{
    apply_spec_overrides, build_typed_bundle, debug_error, debug_request, discover_bundles,
    find_application, get_json, load_bundle, per_file_sha256, select_bundles, DeployArgs,
    LoadedBundle,
};

/// Curated name + description per slug. Bundles not listed fall back to a
/// title-cased slug + a generic description — new examples deploy with zero
/// config; this just preserves nicer copy for the ones we care about.
fn metadata(slug: &str) -> (String, String) {
    match slug {
        "agent-approval-demo" => (
            "Approval demo agent".to_string(),
            "Smallest possible agent that demonstrates approval-gated tool calls — chat with it and ask it to save a note.".to_string(),
        ),
        "agent-builder" => ("Agent Builder".to_string(), "Meta-agent for the platform.".to_string()),
        _ => (capitalize(&slug.replace('-', " ")), format!("Example agent bundle: {slug}.")),
    }
}

/// First char upper, the rest lower — matches Python's `str.capitalize()`.
fn capitalize(s: &str) -> String {
    let mut chars = s.chars();
    match chars.next() {
        None => String::new(),
        Some(first) => first
            .to_uppercase()
            .chain(chars.flat_map(char::to_lowercase))
            .collect(),
    }
}

enum Action {
    Create,
    Update,
    Skip,
}

struct Planned {
    bundle: LoadedBundle,
    spec: Value,
    /// Existing application id, or None when the application must be created.
    app_id: Option<String>,
    /// Live revision to branch from (parent of the new draft), if any.
    live_rev: Option<String>,
    action: Action,
    reason: String,
}

pub fn deploy_agents(args: &DeployArgs) -> Result<()> {
    context().capture_command_invoked("agents_deploy");
    let host = context().client.get_host().clone();

    let bundles = discover_bundles(Path::new(&args.dir))?;
    if bundles.is_empty() {
        anyhow::bail!("no bundles found under {}", args.dir);
    }
    let selected = select_bundles(&bundles, &args.names)?;

    println!();
    println!(
        "Deploy target: {} — {}/{} bundle(s)",
        host.bold(),
        selected.len(),
        bundles.len()
    );
    println!();

    // ── plan ──────────────────────────────────────────────────────────────────
    let mut planned: Vec<Planned> = Vec::new();
    let mut failures: Vec<(String, String)> = Vec::new();
    for root in &selected {
        match plan_bundle(root, &host, args) {
            Ok(p) => planned.push(p),
            Err(e) => {
                let slug = root
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_default();
                println!(
                    "  {}   {} ({})",
                    "ERROR".red().bold(),
                    slug,
                    format!("{e:#}").dimmed()
                );
                failures.push((slug, format!("{e:#}")));
            }
        }
    }

    for p in &planned {
        match p.action {
            Action::Create => println!(
                "  {}  {} ({})",
                "CREATE".green().bold(),
                p.bundle.slug.bold(),
                p.reason.dimmed()
            ),
            Action::Update => println!(
                "  {}  {} ({})",
                "UPDATE".yellow().bold(),
                p.bundle.slug.bold(),
                p.reason.dimmed()
            ),
            Action::Skip => println!(
                "  {}    {} ({})",
                "SKIP".dimmed(),
                p.bundle.slug,
                p.reason.dimmed()
            ),
        }
    }

    let to_apply = planned
        .iter()
        .filter(|p| !matches!(p.action, Action::Skip))
        .count();

    if to_apply == 0 {
        println!();
        println!("Nothing to deploy.");
        return finish(&failures);
    }

    // ── dry-run stops after the plan ────────────────────────────────────────────
    if args.dry_run {
        println!();
        println!("{}", "(dry-run, nothing deployed)".dimmed());
        return finish(&failures);
    }

    // ── confirm ─────────────────────────────────────────────────────────────────
    if !args.yes
        && !matches!(
            Confirm::new(&format!("Deploy {to_apply} bundle(s)?"))
                .with_default(true)
                .prompt(),
            Ok(true)
        )
    {
        println!("Cancelled.");
        return Ok(());
    }
    println!();

    // ── apply ─────────────────────────────────────────────────────────────────
    let mut deployed = 0;
    for p in planned {
        if matches!(p.action, Action::Skip) {
            continue;
        }
        let slug = p.bundle.slug.clone();
        match apply_bundle(p, args) {
            Ok(rev_id) => {
                println!(
                    "  {} {} live at {}",
                    "✓".green(),
                    slug.bold(),
                    rev_id.dimmed()
                );
                deployed += 1;
            }
            Err(e) => {
                println!("  {} {}: {}", "✗".red(), slug, format!("{e:#}").dimmed());
                failures.push((slug, format!("{e:#}")));
            }
        }
    }

    println!();
    println!("{deployed}/{to_apply} bundle(s) deployed.");
    finish(&failures)
}

fn finish(failures: &[(String, String)]) -> Result<()> {
    if failures.is_empty() {
        return Ok(());
    }
    eprintln!();
    eprintln!("{}", "Failed bundles:".red());
    for (slug, msg) in failures {
        eprintln!("  - {slug}: {}", msg.lines().next().unwrap_or(""));
    }
    anyhow::bail!("{} bundle(s) failed", failures.len());
}

/// Load a bundle, apply overrides, and classify it against the live revision —
/// faithfully mirroring seed.py's loose manifest+spec comparison.
fn plan_bundle(root: &Path, host: &str, args: &DeployArgs) -> Result<Planned> {
    let bundle = load_bundle(root)?;
    let spec = apply_spec_overrides(
        &bundle.spec,
        host,
        args.auth_mode.as_deref(),
        args.mcp_url.as_deref(),
    )?;

    let app_id = find_application(&bundle.slug, args.debug)?;
    let (action, reason, live_rev) = match &app_id {
        None => (Action::Create, "new application".to_string(), None),
        Some(id) => {
            let (live_rev, live_manifest, live_spec) = get_live(id, args.debug);
            let target = per_file_sha256(&bundle.files);
            if live_rev.is_none() {
                (Action::Update, "no live revision yet".to_string(), None)
            } else if live_manifest.as_ref() == Some(&target) && live_spec.as_ref() == Some(&spec) {
                (Action::Skip, "matches live".to_string(), live_rev)
            } else if live_manifest.as_ref() != Some(&target) {
                (Action::Update, "bundle drifted".to_string(), live_rev)
            } else {
                (Action::Update, "spec drifted".to_string(), live_rev)
            }
        }
    };

    Ok(Planned {
        bundle,
        spec,
        app_id,
        live_rev,
        action,
        reason,
    })
}

/// Run the full deploy pipeline for one planned bundle. Returns the now-live revision id.
fn apply_bundle(p: Planned, args: &DeployArgs) -> Result<String> {
    let slug = &p.bundle.slug;
    let app_id = match p.app_id {
        Some(id) => id,
        None => create_application(slug, args.debug)?,
    };

    let rev_id = create_draft(slug, &app_id, p.live_rev.as_deref(), &p.spec, args.debug)?;
    push_bundle(
        &app_id,
        &rev_id,
        &build_typed_bundle(&p.bundle, &p.spec),
        args.debug,
    )?;
    patch_spec(&app_id, &rev_id, &p.spec, args.debug)?;
    if args.dummy_secrets {
        ensure_dummy_secrets(slug, &app_id, &rev_id, &p.spec, args.debug)?;
    }
    validate(slug, &app_id, &rev_id, args.debug)?;
    freeze(&app_id, &rev_id, args.debug)?;
    promote(&app_id, &rev_id, args.debug)?;
    Ok(rev_id)
}

// ── pipeline steps ──────────────────────────────────────────────────────────

fn create_application(slug: &str, debug: bool) -> Result<String> {
    let (name, description) = metadata(slug);
    let body = json!({ "name": name, "slug": slug, "description": description, "archived": false });
    let v = post_json("agent_applications/", &body, debug).context("create application")?;
    v.get("id")
        .and_then(Value::as_str)
        .map(str::to_string)
        .context("create application: response missing id")
}

/// `(live_revision_id, {path: sha256}, spec)` for the live revision, or all-None.
/// Read failures collapse to None (mirrors seed.py's status-based fallbacks).
fn get_live(
    app_id: &str,
    debug: bool,
) -> (
    Option<String>,
    Option<HashMap<String, String>>,
    Option<Value>,
) {
    let Ok(app) = get_json(&format!("agent_applications/{app_id}/"), debug) else {
        return (None, None, None);
    };
    let Some(rev_id) = app
        .get("live_revision")
        .and_then(Value::as_str)
        .map(str::to_string)
    else {
        return (None, None, None);
    };
    let spec = get_json(
        &format!("agent_applications/{app_id}/revisions/{rev_id}/"),
        debug,
    )
    .ok()
    .and_then(|r| r.get("spec").cloned());
    let manifest = match get_json(
        &format!("agent_applications/{app_id}/revisions/{rev_id}/manifest/"),
        debug,
    ) {
        Ok(m) => m,
        Err(_) => return (Some(rev_id), None, spec),
    };
    let files = manifest.get("files").and_then(Value::as_array).map(|arr| {
        arr.iter()
            .filter_map(|f| {
                Some((
                    f.get("path").and_then(Value::as_str)?.to_string(),
                    f.get("sha256").and_then(Value::as_str)?.to_string(),
                ))
            })
            .collect::<HashMap<String, String>>()
    });
    (Some(rev_id), files, spec)
}

fn create_draft(
    slug: &str,
    app_id: &str,
    parent: Option<&str>,
    spec: &Value,
    debug: bool,
) -> Result<String> {
    if let Some(parent) = parent {
        // new_draft branches from the live revision, copying its bundle; we then
        // overwrite the bundle + patch the spec to match what we want.
        let body = json!({ "application_id": app_id, "source_revision_id": parent });
        let v = post_json(
            &format!("agent_applications/{app_id}/revisions/new_draft/"),
            &body,
            debug,
        )
        .with_context(|| format!("new_draft for {slug}"))?;
        v.get("revision")
            .and_then(|r| r.get("id"))
            .and_then(Value::as_str)
            .map(str::to_string)
            .context("new_draft: response missing revision.id")
    } else {
        let body = json!({ "application_id": app_id, "bundle_uri": format!("local://{slug}/seed"), "spec": spec });
        let v = post_json(
            &format!("agent_applications/{app_id}/revisions/"),
            &body,
            debug,
        )
        .with_context(|| format!("draft create for {slug}"))?;
        v.get("id")
            .and_then(Value::as_str)
            .map(str::to_string)
            .context("draft create: response missing id")
    }
}

fn push_bundle(app_id: &str, rev_id: &str, typed: &Value, debug: bool) -> Result<()> {
    let client = &context().client;
    let path = format!("agent_applications/{app_id}/revisions/{rev_id}/bundle/");
    debug_request(debug, "PUT", &path);
    client
        .send_put(client.project_url(&path)?, |req| req.json(typed))
        .inspect_err(|e| debug_error(debug, e))
        .context("bundle update")?;
    Ok(())
}

fn patch_spec(app_id: &str, rev_id: &str, spec: &Value, debug: bool) -> Result<()> {
    let client = &context().client;
    let path = format!("agent_applications/{app_id}/revisions/{rev_id}/");
    debug_request(debug, "PATCH", &path);
    client
        .send_request(reqwest::Method::PATCH, client.project_url(&path)?, |req| {
            req.json(&json!({ "spec": spec }))
        })
        .inspect_err(|e| debug_error(debug, e))
        .context("spec patch")?;
    Ok(())
}

fn validate(slug: &str, app_id: &str, rev_id: &str, debug: bool) -> Result<()> {
    let v = post_json(
        &format!("agent_applications/{app_id}/revisions/{rev_id}/validate/"),
        &json!({}),
        debug,
    )
    .with_context(|| format!("validate for {slug}"))?;
    if !v.get("ok").and_then(Value::as_bool).unwrap_or(false) {
        anyhow::bail!(
            "validate failed for {slug}: {}",
            serde_json::to_string_pretty(&v).unwrap_or_default()
        );
    }
    Ok(())
}

fn freeze(app_id: &str, rev_id: &str, debug: bool) -> Result<()> {
    post_json(
        &format!("agent_applications/{app_id}/revisions/{rev_id}/freeze/"),
        &json!({}),
        debug,
    )
    .context("freeze")?;
    Ok(())
}

fn promote(app_id: &str, rev_id: &str, debug: bool) -> Result<()> {
    post_json(
        &format!("agent_applications/{app_id}/revisions/{rev_id}/promote/"),
        &json!({}),
        debug,
    )
    .context("promote")?;
    Ok(())
}

/// Set placeholder values for any required secret not already set, so secret-gated
/// agents can promote locally. Never overwrites an existing value.
fn ensure_dummy_secrets(
    slug: &str,
    app_id: &str,
    rev_id: &str,
    spec: &Value,
    debug: bool,
) -> Result<()> {
    let client = &context().client;
    let mut set: Vec<String> = Vec::new();
    for key in required_secret_keys(spec) {
        let base = format!("agent_applications/{app_id}/revisions/{rev_id}/env_keys/{key}/");
        let is_set = get_json(&base, debug)
            .ok()
            .and_then(|p| p.get("is_set").and_then(Value::as_bool))
            .unwrap_or(false);
        if is_set {
            continue;
        }
        debug_request(debug, "PUT", &base);
        client
            .send_put(client.project_url(&base)?, |req| {
                req.json(&json!({ "value": format!("placeholder-{key}") }))
            })
            .inspect_err(|e| debug_error(debug, e))
            .with_context(|| format!("set placeholder secret {key}"))?;
        set.push(key);
    }
    if !set.is_empty() {
        println!(
            "  {} {}: placeholder secrets {}",
            "→".cyan(),
            slug,
            set.join(", ").dimmed()
        );
    }
    Ok(())
}

/// Secret keys a bundle needs before promote: declared `spec.secrets[]` plus
/// per-trigger required keys (slack). Order-preserving + de-duped.
fn required_secret_keys(spec: &Value) -> Vec<String> {
    let mut keys: Vec<String> = Vec::new();
    if let Some(secrets) = spec.get("secrets").and_then(Value::as_array) {
        for s in secrets {
            if let Some(k) = s.get("key").and_then(Value::as_str).or_else(|| s.as_str()) {
                if !keys.iter().any(|x| x == k) {
                    keys.push(k.to_string());
                }
            }
        }
    }
    if let Some(triggers) = spec.get("triggers").and_then(Value::as_array) {
        for t in triggers {
            if t.get("type").and_then(Value::as_str) == Some("slack") {
                for k in ["SLACK_SIGNING_SECRET", "SLACK_BOT_TOKEN"] {
                    if !keys.iter().any(|x| x == k) {
                        keys.push(k.to_string());
                    }
                }
            }
        }
    }
    keys
}

/// POST a project-scoped path with a JSON body and parse the response. Non-2xx is an Err.
fn post_json(path: &str, body: &Value, debug: bool) -> Result<Value> {
    let client = &context().client;
    debug_request(debug, "POST", path);
    let resp = client
        .send_post(client.project_url(path)?, |req| req.json(body))
        .inspect_err(|e| debug_error(debug, e))?;
    resp.json()
        .with_context(|| format!("parsing response for {path}"))
}
