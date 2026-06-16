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

fn adjacent_bundle_dir() -> Option<PathBuf> {
    Some(env::current_exe().ok()?.parent()?.to_path_buf())
}

fn bundle_candidates(
    executable_dir: Option<&Path>,
    install_dir: Option<&Path>,
    development_dir: &Path,
) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Some(bundle_dir) = executable_dir {
        candidates.extend([
            bundle_dir.join("lib").join(API_CLI_BUNDLE),
            bundle_dir.join(API_CLI_BUNDLE),
        ]);
    }

    if let Some(install_dir) = install_dir {
        candidates.extend([
            install_dir.join("lib").join(API_CLI_BUNDLE),
            install_dir.join("cli/lib").join(API_CLI_BUNDLE),
            install_dir.join("api-cli").join(API_CLI_BUNDLE),
            install_dir.join(API_CLI_BUNDLE),
        ]);
    }

    candidates.push(development_dir.join("lib").join(API_CLI_BUNDLE));
    candidates
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

    let executable_dir = adjacent_bundle_dir();
    let install_dir = default_install_dir();
    for candidate in bundle_candidates(
        executable_dir.as_deref(),
        install_dir.as_deref(),
        Path::new(env!("CARGO_MANIFEST_DIR")),
    ) {
        if let Some(resolved) = canonicalize_file(&candidate) {
            return Ok(resolved);
        }
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

#[cfg(test)]
mod tests {
    use std::fs;

    use super::*;

    #[test]
    fn bundle_candidates_prefer_the_bundle_next_to_the_executable() {
        let executable_dir = PathBuf::from("node_modules").join(".bin_real");
        let install_dir = PathBuf::from("home").join(".posthog");
        let development_dir = PathBuf::from("repo").join("cli");

        let candidates =
            bundle_candidates(Some(&executable_dir), Some(&install_dir), &development_dir);

        assert_eq!(
            candidates[0],
            executable_dir.join("lib").join(API_CLI_BUNDLE)
        );
        assert_eq!(candidates[1], executable_dir.join(API_CLI_BUNDLE));
        assert_eq!(candidates[2], install_dir.join("lib").join(API_CLI_BUNDLE));
        assert_eq!(
            candidates.last(),
            Some(&development_dir.join("lib").join(API_CLI_BUNDLE))
        );
    }

    #[test]
    fn canonicalize_file_rejects_directories() {
        let temp_dir = tempfile::tempdir().expect("create temp dir");

        assert_eq!(canonicalize_file(temp_dir.path()), None);
    }

    #[test]
    fn adjacent_bundle_path_is_usable_without_a_home_install() {
        let temp_dir = tempfile::tempdir().expect("create temp dir");
        let executable_dir = temp_dir.path().join("node_modules").join(".bin_real");
        let install_dir = temp_dir.path().join("home").join(".posthog");
        let development_dir = temp_dir.path().join("repo").join("cli");
        let adjacent_bundle = executable_dir.join("lib").join(API_CLI_BUNDLE);
        let legacy_bundle = install_dir.join("lib").join(API_CLI_BUNDLE);

        fs::create_dir_all(adjacent_bundle.parent().expect("adjacent parent"))
            .expect("create adjacent lib dir");
        fs::create_dir_all(legacy_bundle.parent().expect("legacy parent"))
            .expect("create legacy lib dir");
        fs::write(&adjacent_bundle, "adjacent").expect("write adjacent bundle");
        fs::write(&legacy_bundle, "legacy").expect("write legacy bundle");

        let resolved =
            bundle_candidates(Some(&executable_dir), Some(&install_dir), &development_dir)
                .into_iter()
                .find_map(|candidate| canonicalize_file(&candidate));

        assert_eq!(
            resolved,
            Some(
                adjacent_bundle
                    .canonicalize()
                    .expect("canonicalize adjacent bundle")
            )
        );
    }
}
