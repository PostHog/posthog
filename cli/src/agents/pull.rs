use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use colored::Colorize;
use serde::Serialize;
use serde_json::Value;
use walkdir::WalkDir;

use crate::invocation_context::context;

use super::{
    discover_bundles, find_application, get_json, get_typed_bundle, select_bundles, slug_of,
    PullArgs,
};

/// Top-level spec keys deploy strips before upload, so the platform never stores
/// them. Preserved from the on-disk `spec.json` when rewriting it.
const LOCAL_ONLY_SPEC_KEYS: [&str; 1] = ["resume"];

pub fn pull_agents(args: &PullArgs) -> Result<()> {
    context().capture_command_invoked("agents_pull");

    let bundles = discover_bundles(Path::new(&args.dir))?;
    if bundles.is_empty() {
        anyhow::bail!("no bundles found under {}", args.dir);
    }
    let selected = select_bundles(&bundles, &args.names)?;

    println!();
    println!(
        "Pull source: {} — {}/{} bundle(s)",
        context().client.get_host().bold(),
        selected.len(),
        bundles.len()
    );
    println!();

    let mut failures: Vec<(String, String)> = Vec::new();
    for root in &selected {
        if let Err(e) = pull_bundle(root, args) {
            let slug = slug_of(root).unwrap_or_default();
            println!("  {} {}: {}", "✗".red(), slug, format!("{e:#}").dimmed());
            failures.push((slug, format!("{e:#}")));
        }
    }

    println!();
    println!(
        "{}/{} bundle(s) ok.",
        selected.len() - failures.len(),
        selected.len()
    );
    if !failures.is_empty() {
        anyhow::bail!("{} bundle(s) failed", failures.len());
    }
    Ok(())
}

fn pull_bundle(root: &Path, args: &PullArgs) -> Result<()> {
    let slug = slug_of(root).context("bundle has no directory name")?;
    let Some(app_id) = find_application(&slug, args.debug)? else {
        println!("  {slug}: no application on the platform — nothing to pull");
        return Ok(());
    };
    let Some(rev_id) = pick_revision(&app_id, args.latest, args.debug)? else {
        println!("  {slug}: no revision to pull (not promoted yet? try --latest)");
        return Ok(());
    };

    let bundle = get_typed_bundle(&app_id, &rev_id, args.debug)?;
    println!("  {slug}: pulling revision {rev_id}");

    let mut changed = 0u32;

    // agent.md — the system prompt.
    let agent_md = bundle.get("agent_md").and_then(Value::as_str).unwrap_or("");
    if write_if_changed(root, "agent.md", agent_md, args.dry_run)? {
        changed += 1;
    }

    // Skills — one folder per skill at the platform-canonical path. Bodies
    // round-trip exactly; this is the common case (Agent Builder prose edits).
    let mut pulled_skills: HashSet<String> = HashSet::new();
    if let Some(skills) = bundle.get("skills").and_then(Value::as_array) {
        for s in skills {
            let Some(sid) = s.get("id").and_then(Value::as_str) else {
                continue;
            };
            let rel = format!("skills/{sid}/SKILL.md");
            pulled_skills.insert(rel.clone());
            let body = s.get("body").and_then(Value::as_str).unwrap_or("");
            if write_if_changed(root, &rel, body, args.dry_run)? {
                changed += 1;
            }
        }
    }

    // Custom tool sources (deploy doesn't push these, but the Agent Builder may
    // have added one on the platform). `source` may be "" but not null.
    let mut pulled_tools: HashSet<String> = HashSet::new();
    if let Some(tools) = bundle.get("tools").and_then(Value::as_array) {
        for t in tools {
            let (Some(tid), Some(source)) = (
                t.get("id").and_then(Value::as_str),
                t.get("source").and_then(Value::as_str),
            ) else {
                continue;
            };
            pulled_tools.insert(format!("tools/{tid}"));
            if write_if_changed(
                root,
                &format!("tools/{tid}/source.ts"),
                source,
                args.dry_run,
            )? {
                changed += 1;
            }
        }
    }

    // spec.json — opt-in. The platform stores the FROZEN spec (defaults filled,
    // skill descriptions re-derived at freeze), so this rewrites spec.json into
    // that normalised shape. Off by default; review the diff.
    if args.spec {
        let on_disk: Value = fs::read_to_string(root.join("spec.json"))
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_else(|| Value::Object(Default::default()));
        let full = get_full_spec(&app_id, &rev_id, args.debug)?;
        let serialized = serialize_spec(&reconstruct_spec(&full, &on_disk))?;
        if write_if_changed(root, "spec.json", &serialized, args.dry_run)? {
            changed += 1;
        }
    } else {
        println!(
            "  {slug}: spec.json not pulled (pass --spec to also pull spec/trigger/tool changes)"
        );
    }

    prune_orphans(
        root,
        &slug,
        &pulled_skills,
        &pulled_tools,
        args.prune,
        args.dry_run,
    )?;

    if changed == 0 {
        println!("  {slug}: content up to date — nothing changed");
    }
    Ok(())
}

// ── platform reads ────────────────────────────────────────────────────────────

/// The revision to pull: the live one by default, or the newest revision (any
/// state) with `--latest`. None if there's nothing to pull.
fn pick_revision(app_id: &str, latest: bool, debug: bool) -> Result<Option<String>> {
    let app =
        get_json(&format!("agent_applications/{app_id}/"), debug).context("read application")?;
    let live = app
        .get("live_revision")
        .and_then(Value::as_str)
        .map(str::to_string);
    if !latest {
        return Ok(live);
    }
    let payload = get_json(&format!("agent_applications/{app_id}/revisions/"), debug)
        .context("list revisions")?;
    let revs = payload
        .get("results")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if revs.is_empty() {
        return Ok(live);
    }
    let newest = revs.iter().max_by(|a, b| {
        let key = |r: &Value| {
            r.get("created_at")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string()
        };
        key(a).cmp(&key(b))
    });
    Ok(newest
        .and_then(|r| r.get("id").and_then(Value::as_str))
        .map(str::to_string))
}

/// The full frozen spec (includes derived `skills[]` + `tools[]`).
fn get_full_spec(app_id: &str, rev_id: &str, debug: bool) -> Result<Value> {
    let rev = get_json(
        &format!("agent_applications/{app_id}/revisions/{rev_id}/"),
        debug,
    )
    .with_context(|| format!("read revision {rev_id}"))?;
    rev.get("spec")
        .filter(|s| s.is_object())
        .cloned()
        .with_context(|| format!("revision {rev_id} has no spec"))
}

// ── disk writes ────────────────────────────────────────────────────────────────

/// Write `content` to `rel` under the bundle only if it differs. Logs
/// `+ added` / `~ updated` (silent when unchanged). Honors dry-run.
fn write_if_changed(root: &Path, rel: &str, content: &str, dry_run: bool) -> Result<bool> {
    let dest = root.join(rel);
    let existed = dest.is_file();
    if existed && fs::read_to_string(&dest).ok().as_deref() == Some(content) {
        return Ok(false);
    }
    let verb = if existed { "~ updated" } else { "+ added" };
    println!("    {verb} {rel}");
    if !dry_run {
        if let Some(parent) = dest.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&dest, content).with_context(|| format!("writing {rel}"))?;
    }
    Ok(true)
}

/// Match the on-disk bundle convention: 4-space indent, trailing newline,
/// non-ASCII left intact (prompts use em-dashes etc.).
fn serialize_spec(spec: &Value) -> Result<String> {
    let mut buf = Vec::new();
    let fmt = serde_json::ser::PrettyFormatter::with_indent(b"    ");
    let mut ser = serde_json::Serializer::with_formatter(&mut buf, fmt);
    spec.serialize(&mut ser).context("serialize spec")?;
    let body = String::from_utf8(buf).context("spec is not valid UTF-8")?;
    Ok(format!("{body}\n"))
}

/// The spec to write: the platform's frozen spec plus any local-only keys
/// (`resume`) carried over from the existing file.
// ponytail: serde_json::Value objects sort their keys (no `preserve_order`
// feature), so the on-disk key order isn't preserved across a --spec pull.
// Enable serde_json `preserve_order` if minimal --spec diffs ever matter.
fn reconstruct_spec(platform_spec: &Value, on_disk: &Value) -> Value {
    let mut merged = platform_spec.clone();
    if let Some(obj) = merged.as_object_mut() {
        for key in LOCAL_ONLY_SPEC_KEYS {
            if !obj.contains_key(key) {
                if let Some(v) = on_disk.get(key) {
                    obj.insert(key.to_string(), v.clone());
                }
            }
        }
    }
    merged
}

/// On-disk skills/tools the platform no longer has. With `--prune`, delete them;
/// otherwise warn so a stale local file doesn't silently re-deploy.
fn prune_orphans(
    root: &Path,
    slug: &str,
    pulled_skills: &HashSet<String>,
    pulled_tools: &HashSet<String>,
    prune: bool,
    dry_run: bool,
) -> Result<()> {
    let skills_dir = root.join("skills");
    if skills_dir.is_dir() {
        let mut files: Vec<PathBuf> = WalkDir::new(&skills_dir)
            .sort_by_file_name()
            .into_iter()
            .filter_map(|e| e.ok().map(walkdir::DirEntry::into_path))
            .filter(|p| p.is_file() && p.file_name().is_some_and(|n| n == "SKILL.md"))
            .collect();
        files.sort();
        for f in files {
            let rel = f.strip_prefix(root)?.to_string_lossy().replace('\\', "/");
            if pulled_skills.contains(&rel) {
                continue;
            }
            // Remove the skill's folder, unless the SKILL.md sits directly in skills/.
            let target = match f.parent() {
                Some(parent) if parent != skills_dir.as_path() => parent.to_path_buf(),
                _ => f.clone(),
            };
            handle_orphan(slug, &target, &rel, prune, dry_run)?;
        }
    }

    let tools_dir = root.join("tools");
    if tools_dir.is_dir() {
        let mut dirs: Vec<PathBuf> = fs::read_dir(&tools_dir)?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.is_dir())
            .collect();
        dirs.sort();
        for d in dirs {
            let rel = d.strip_prefix(root)?.to_string_lossy().replace('\\', "/");
            if pulled_tools.contains(&rel) {
                continue;
            }
            handle_orphan(slug, &d, &rel, prune, dry_run)?;
        }
    }
    Ok(())
}

fn handle_orphan(slug: &str, target: &Path, rel: &str, prune: bool, dry_run: bool) -> Result<()> {
    if !prune {
        println!(
            "  {slug}: {} on disk but not on platform: {rel} (pass --prune to remove)",
            "!".yellow()
        );
        return Ok(());
    }
    println!("  {slug}: - removed {rel}");
    if dry_run {
        return Ok(());
    }
    if target.is_dir() {
        fs::remove_dir_all(target).with_context(|| format!("removing {rel}"))?;
    } else if target.is_file() {
        fs::remove_file(target).with_context(|| format!("removing {rel}"))?;
    }
    Ok(())
}
