//! `posthog-cli init` — project setup for the PostHog CLI.
//!
//! When `--agent` is passed, writes the coding-agent steering block into the
//! target file (default `AGENTS.md`) without prompting. Without it, asks
//! interactively whether the user is using a coding agent and only writes the
//! block if they say yes.
//!
//! The block is delimited by `posthog:cli` markers, so re-running replaces it
//! in place rather than appending a duplicate.

use anyhow::{Context, Result};
use std::fs;
use std::path::Path;

const STEERING_BLOCK: &str = include_str!("steering.md");
const START_MARKER: &str = "<!-- posthog:cli:start -->";
const END_MARKER: &str = "<!-- posthog:cli:end -->";

pub fn run(path: &str, agent: bool) -> Result<()> {
    let install_steering = if agent {
        true
    } else {
        inquire::Confirm::new("Are you using a coding agent (e.g. Claude Code, Cursor, Copilot)?")
            .with_default(true)
            .with_help_message("If yes, we'll add a steering block to your AGENTS.md so your agent can discover and use the CLI")
            .prompt()
            .context("Failed to read response")?
    };

    if install_steering {
        write_steering(path)?;
    } else {
        println!("Skipped agent steering block. You can add it later with `posthog-cli init --agent`.");
    }

    Ok(())
}

fn write_steering(path: &str) -> Result<()> {
    let block = STEERING_BLOCK.trim_end_matches('\n');
    let existing = fs::read_to_string(path).unwrap_or_default();

    let (content, action) = merge(&existing, block);

    if let Some(parent) = Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .with_context(|| format!("Failed to create {}", parent.display()))?;
        }
    }
    fs::write(path, content).with_context(|| format!("Failed to write {path}"))?;

    println!("posthog-cli: {action} the PostHog CLI section in {path}");
    println!("Next: run `posthog-cli login` to authenticate (interactive).");
    Ok(())
}

/// Returns the new file content and a human verb describing what happened.
fn merge(existing: &str, block: &str) -> (String, &'static str) {
    if let (Some(start), Some(end)) = (existing.find(START_MARKER), existing.find(END_MARKER)) {
        if end > start {
            let end_idx = end + END_MARKER.len();
            let mut out = String::with_capacity(existing.len());
            out.push_str(&existing[..start]);
            out.push_str(block);
            out.push_str(&existing[end_idx..]);
            return (out, "updated");
        }
    }
    if existing.trim().is_empty() {
        return (format!("{block}\n"), "created");
    }
    let separator = if existing.ends_with('\n') {
        "\n"
    } else {
        "\n\n"
    };
    (format!("{existing}{separator}{block}\n"), "added")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block() -> &'static str {
        STEERING_BLOCK.trim_end_matches('\n')
    }

    #[test]
    fn creates_into_empty() {
        let (content, action) = merge("", block());
        assert_eq!(action, "created");
        assert!(content.starts_with(START_MARKER));
        assert!(content.trim_end().ends_with(END_MARKER));
    }

    #[test]
    fn appends_preserving_existing() {
        let existing = "# My project rules\n\nDo the thing.\n";
        let (content, action) = merge(existing, block());
        assert_eq!(action, "added");
        assert!(content.starts_with("# My project rules"));
        assert!(content.contains(START_MARKER));
        assert!(content.contains("Do the thing.\n\n<!-- posthog:cli:start -->"));
    }

    #[test]
    fn replaces_between_markers_idempotently() {
        let existing = "# Top\n\n<!-- posthog:cli:start -->\nOLD CONTENT\n<!-- posthog:cli:end -->\n\n# Bottom\n";
        let (once, action) = merge(existing, block());
        assert_eq!(action, "updated");
        assert!(once.starts_with("# Top"));
        assert!(once.contains("# Bottom"));
        assert!(!once.contains("OLD CONTENT"));
        assert_eq!(once.matches(START_MARKER).count(), 1);

        let (twice, _) = merge(&once, block());
        assert_eq!(once, twice);
        assert_eq!(twice.matches(START_MARKER).count(), 1);
    }
}
