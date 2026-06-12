use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{bail, Context, Result};

use crate::error::CapturedError;
use crate::invocation_context::InvocationContext;

const API_CLI_BUNDLE: &str = "posthog-api-cli.mjs";
const ANALYTICS_HOST: &str = "https://us.i.posthog.com";

fn canonicalize_file(path: &Path) -> Option<PathBuf> {
    let resolved = path.canonicalize().ok()?;
    if resolved.is_file() {
        Some(resolved)
    } else {
        None
    }
}

fn default_install_dir() -> Option<PathBuf> {
    Some(dirs::home_dir()?.join(".posthog"))
}

fn find_script() -> Result<PathBuf> {
    if let Some(path) = env::var_os("POSTHOG_API_CLI_PATH") {
        if path.is_empty() {
            bail!("POSTHOG_API_CLI_PATH is set but empty.");
        }
        let path = PathBuf::from(path);
        let resolved = path.canonicalize().with_context(|| {
            format!(
                "POSTHOG_API_CLI_PATH is set to `{}`, but that file could not be found.",
                path.display()
            )
        })?;
        if !resolved.is_file() {
            bail!(
                "POSTHOG_API_CLI_PATH is set to `{}`, but it is not a file.",
                resolved.display()
            );
        }
        return Ok(resolved);
    }

    if let Some(install_dir) = default_install_dir() {
        for candidate in [
            install_dir.join("lib").join(API_CLI_BUNDLE),
            install_dir.join("cli/lib").join(API_CLI_BUNDLE),
            install_dir.join("api-cli").join(API_CLI_BUNDLE),
            install_dir.join(API_CLI_BUNDLE),
        ] {
            if let Some(resolved) = canonicalize_file(&candidate) {
                return Ok(resolved);
            }
        }
    }

    let development_bundle = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("lib")
        .join(API_CLI_BUNDLE);
    if let Some(resolved) = canonicalize_file(&development_bundle) {
        return Ok(resolved);
    }

    bail!(
        "Could not find the PostHog API CLI bundle. Reinstall posthog-cli, or set POSTHOG_API_CLI_PATH to a trusted bundle."
    )
}

fn has_any_env(names: &[&str]) -> bool {
    names.iter().any(|name| env::var(name).is_ok())
}

fn inject_credentials(cmd: &mut Command, invocation_context: Option<&InvocationContext>) {
    let Some(invocation_context) = invocation_context else {
        return;
    };
    let config = &invocation_context.config;

    if !has_any_env(&[
        "POSTHOG_API_KEY",
        "POSTHOG_CLI_API_KEY",
        "POSTHOG_CLI_TOKEN",
    ]) {
        cmd.env("POSTHOG_CLI_API_KEY", &config.api_key);
    }

    if !has_any_env(&[
        "POSTHOG_PROJECT_ID",
        "POSTHOG_CLI_PROJECT_ID",
        "POSTHOG_CLI_ENV_ID",
    ]) {
        cmd.env("POSTHOG_CLI_PROJECT_ID", &config.env_id);
    }

    if !has_any_env(&["POSTHOG_HOST", "POSTHOG_CLI_HOST"]) {
        cmd.env("POSTHOG_CLI_HOST", &config.host);
    }
}

fn inject_analytics_env(cmd: &mut Command) {
    if let Some(token) = option_env!("POSTHOG_API_TOKEN") {
        if env::var_os("POSTHOG_ANALYTICS_API_KEY").is_none() {
            cmd.env("POSTHOG_ANALYTICS_API_KEY", token);
        }
        if env::var_os("POSTHOG_ANALYTICS_HOST").is_none() {
            cmd.env("POSTHOG_ANALYTICS_HOST", ANALYTICS_HOST);
        }
    }
}

pub fn run(
    args: Vec<String>,
    host_override: Option<String>,
    invocation_context: Option<&InvocationContext>,
) -> Result<(), CapturedError> {
    let script = find_script().map_err(CapturedError::from)?;
    let mut cmd = Command::new("node");
    cmd.arg(script);
    cmd.args(args);
    cmd.env("POSTHOG_CLI_VERSION", env!("CARGO_PKG_VERSION"));

    inject_credentials(&mut cmd, invocation_context);
    inject_analytics_env(&mut cmd);

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
