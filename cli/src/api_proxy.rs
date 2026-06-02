use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{bail, Context, Result};

use crate::error::CapturedError;
use crate::utils::auth::{get_token, Token};

fn find_repo_root() -> Option<PathBuf> {
    let mut dir = env::current_dir().ok()?;
    for _ in 0..10 {
        if dir.join("posthog/settings/web.py").exists() {
            return Some(dir);
        }
        if !dir.pop() {
            break;
        }
    }
    None
}

fn find_script() -> Result<PathBuf> {
    if let Ok(path) = env::var("POSTHOG_API_CLI_PATH") {
        let path = PathBuf::from(path);
        if path.exists() {
            return Ok(path);
        }
    }

    if let Ok(exe) = env::current_exe() {
        if let Some(bin_dir) = exe.parent() {
            for candidate in [
                bin_dir.join("../lib/posthog-api-cli.mjs"),
                bin_dir.join("../lib/api-cli/posthog-api-cli.mjs"),
            ] {
                if candidate.exists() {
                    return candidate
                        .canonicalize()
                        .context("Failed to canonicalize bundled API CLI path");
                }
            }
        }
    }

    if let Some(repo_root) = find_repo_root() {
        let built = repo_root.join("services/mcp/dist/posthog-api-cli.mjs");
        if built.exists() {
            return Ok(built);
        }
    }

    bail!(
        "Could not find the PostHog API CLI bundle. Run `pnpm --filter=@posthog/mcp build:cli` from the PostHog repository, or set POSTHOG_API_CLI_PATH."
    )
}

fn has_any_env(names: &[&str]) -> bool {
    names.iter().any(|name| env::var(name).is_ok())
}

fn inject_credentials(cmd: &mut Command) {
    let token = match get_token() {
        Ok(token) => token,
        Err(_) => return,
    };

    let Token {
        token,
        env_id,
        host,
    } = token;

    if !has_any_env(&[
        "POSTHOG_API_KEY",
        "POSTHOG_CLI_API_KEY",
        "POSTHOG_CLI_TOKEN",
    ]) {
        cmd.env("POSTHOG_CLI_API_KEY", token);
    }

    if !has_any_env(&[
        "POSTHOG_PROJECT_ID",
        "POSTHOG_CLI_PROJECT_ID",
        "POSTHOG_CLI_ENV_ID",
    ]) {
        cmd.env("POSTHOG_CLI_PROJECT_ID", env_id);
    }

    if !has_any_env(&["POSTHOG_HOST", "POSTHOG_CLI_HOST"]) {
        if let Some(host) = host {
            cmd.env("POSTHOG_CLI_HOST", host);
        }
    }
}

pub fn run(args: Vec<String>, host_override: Option<String>) -> Result<(), CapturedError> {
    let script = find_script().map_err(CapturedError::from)?;
    let mut cmd = Command::new("node");
    cmd.arg(script);
    cmd.args(args);
    cmd.env("POSTHOG_CLI_VERSION", env!("CARGO_PKG_VERSION"));

    inject_credentials(&mut cmd);

    if let Some(host) = host_override {
        cmd.env("POSTHOG_CLI_HOST", host);
    }

    let status = cmd
        .status()
        .with_context(|| {
            format!(
                "Failed to execute `{}`. Is Node.js installed?",
                Path::new("node").display()
            )
        })
        .map_err(CapturedError::from)?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}
