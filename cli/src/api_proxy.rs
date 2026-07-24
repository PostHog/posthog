use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::{env, fs};

use thiserror::Error;

use crate::error::CapturedError;
use crate::invocation_context::{current_invocation_id, InvocationContext};
use crate::utils::homedir::posthog_home_dir_if_available;

const API_CLI_BUNDLE: &str = "posthog-api-cli.mjs";
const ANALYTICS_HOST: &str = "https://us.i.posthog.com";

include!(concat!(env!("OUT_DIR"), "/api_cli_bundle.rs"));

/// Which step of writing the embedded bundle to disk failed. Variant names are
/// sent to telemetry (they carry no paths or user data), so keep them stable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MaterializeStep {
    CreateDir,
    Write,
    Canonicalize,
}

impl MaterializeStep {
    fn as_str(self) -> &'static str {
        match self {
            MaterializeStep::CreateDir => "create_dir",
            MaterializeStep::Write => "write",
            MaterializeStep::Canonicalize => "canonicalize",
        }
    }
}

#[derive(Error, Debug)]
pub enum ApiProxyError {
    #[error("POSTHOG_API_CLI_PATH is set but empty.")]
    ConfiguredPathEmpty,
    #[error("POSTHOG_API_CLI_PATH is set to `{path}`, but that file could not be found.")]
    ConfiguredPathMissing {
        path: String,
        #[source]
        source: io::Error,
    },
    #[error("POSTHOG_API_CLI_PATH is set to `{path}`, but it is not a file.")]
    ConfiguredPathNotAFile { path: String },
    #[error(
        "This posthog-cli build does not embed the PostHog API CLI bundle, and no previously \
         installed bundle was found. Reinstall posthog-cli from an official release, or set \
         POSTHOG_API_CLI_PATH to a trusted bundle."
    )]
    BundleNotEmbedded,
    #[error(
        "Could not determine a home directory to install the PostHog API CLI bundle into. Set \
         POSTHOG_HOME to a writable directory, or POSTHOG_API_CLI_PATH to a trusted bundle."
    )]
    HomeDirUnavailable,
    #[error(
        "Failed to install the PostHog API CLI bundle to `{path}`. Make sure the directory is \
         writable (sandboxed environments often block writes to the home directory), set \
         POSTHOG_HOME to a writable directory, or set POSTHOG_API_CLI_PATH to a trusted bundle."
    )]
    MaterializeFailed {
        step: MaterializeStep,
        path: String,
        #[source]
        source: io::Error,
    },
    #[error("Failed to execute `node`. The `api` command needs Node.js installed and on PATH.")]
    NodeSpawnFailed {
        #[source]
        source: io::Error,
    },
}

impl ApiProxyError {
    /// Coarse failure class for telemetry. Never contains paths or user data.
    pub fn telemetry_kind(&self) -> &'static str {
        match self {
            ApiProxyError::ConfiguredPathEmpty
            | ApiProxyError::ConfiguredPathMissing { .. }
            | ApiProxyError::ConfiguredPathNotAFile { .. } => "configured_path_invalid",
            ApiProxyError::BundleNotEmbedded => "bundle_not_embedded",
            ApiProxyError::HomeDirUnavailable => "home_dir_unavailable",
            ApiProxyError::MaterializeFailed { .. } => "materialize_failed",
            ApiProxyError::NodeSpawnFailed { .. } => "node_spawn_failed",
        }
    }

    pub fn telemetry_step(&self) -> Option<&'static str> {
        match self {
            ApiProxyError::MaterializeFailed { step, .. } => Some(step.as_str()),
            _ => None,
        }
    }

    /// The underlying `io::ErrorKind` as a stable identifier (e.g. `PermissionDenied`).
    pub fn telemetry_io_error_kind(&self) -> Option<String> {
        let source = match self {
            ApiProxyError::ConfiguredPathMissing { source, .. } => source,
            ApiProxyError::MaterializeFailed { source, .. } => source,
            ApiProxyError::NodeSpawnFailed { source } => source,
            _ => return None,
        };
        Some(format!("{:?}", source.kind()))
    }
}

/// Resolves `path` to an absolute, symlink-free path. Uses `dunce` rather than
/// `Path::canonicalize` because on Windows the latter returns an extended-length
/// verbatim path (`\\?\C:\...`) that Node's `.mjs` main-module resolution can't
/// handle — it dies with `EISDIR` before any tool logic runs. `dunce` strips the
/// `\\?\` prefix when the path is short enough, and is a no-op on Unix.
fn canonicalize_file(path: &Path) -> Option<PathBuf> {
    let resolved = dunce::canonicalize(path).ok()?;
    if resolved.is_file() {
        Some(resolved)
    } else {
        None
    }
}

fn default_install_dir() -> Option<PathBuf> {
    posthog_home_dir_if_available()
}

fn embedded_bundle_path(install_dir: &Path) -> PathBuf {
    install_dir
        .join("api-cli")
        .join(env!("CARGO_PKG_VERSION"))
        .join(API_CLI_BUNDLE)
}

fn materialize_embedded_script(
    bundle: Option<&[u8]>,
    install_dir: Option<&Path>,
) -> Result<PathBuf, ApiProxyError> {
    let Some(bundle) = bundle else {
        return Err(ApiProxyError::BundleNotEmbedded);
    };
    let Some(install_dir) = install_dir else {
        return Err(ApiProxyError::HomeDirUnavailable);
    };
    let path = embedded_bundle_path(install_dir);
    let materialize_failed =
        |step: MaterializeStep, source: io::Error| ApiProxyError::MaterializeFailed {
            step,
            path: path.display().to_string(),
            source,
        };

    let parent = path
        .parent()
        .expect("embedded bundle path always has a parent directory");
    fs::create_dir_all(parent)
        .map_err(|source| materialize_failed(MaterializeStep::CreateDir, source))?;
    fs::write(&path, bundle)
        .map_err(|source| materialize_failed(MaterializeStep::Write, source))?;
    let resolved = dunce::canonicalize(&path)
        .map_err(|source| materialize_failed(MaterializeStep::Canonicalize, source))?;
    if !resolved.is_file() {
        return Err(materialize_failed(
            MaterializeStep::Canonicalize,
            io::Error::new(
                io::ErrorKind::InvalidData,
                "materialized bundle is not a regular file",
            ),
        ));
    }
    Ok(resolved)
}

fn legacy_bundle_candidates(install_dir: Option<&Path>, development_dir: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

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

/// Resolves the bundle: prefer the embedded copy, fall back to legacy install
/// layouts, and if everything misses report the materialization failure (the
/// specific cause) rather than a generic not-found error.
fn resolve_script(
    bundle: Option<&[u8]>,
    install_dir: Option<&Path>,
    development_dir: &Path,
) -> Result<PathBuf, ApiProxyError> {
    let materialize_error = match materialize_embedded_script(bundle, install_dir) {
        Ok(resolved) => return Ok(resolved),
        Err(error) => error,
    };

    for candidate in legacy_bundle_candidates(install_dir, development_dir) {
        if let Some(resolved) = canonicalize_file(&candidate) {
            return Ok(resolved);
        }
    }

    Err(materialize_error)
}

fn find_script() -> Result<PathBuf, ApiProxyError> {
    if let Some(path) = env::var_os("POSTHOG_API_CLI_PATH") {
        if path.is_empty() {
            return Err(ApiProxyError::ConfiguredPathEmpty);
        }
        let path = PathBuf::from(path);
        let resolved =
            dunce::canonicalize(&path).map_err(|source| ApiProxyError::ConfiguredPathMissing {
                path: path.display().to_string(),
                source,
            })?;
        if !resolved.is_file() {
            return Err(ApiProxyError::ConfiguredPathNotAFile {
                path: resolved.display().to_string(),
            });
        }
        return Ok(resolved);
    }

    resolve_script(
        EMBEDDED_API_CLI_BUNDLE,
        default_install_dir().as_deref(),
        Path::new(env!("CARGO_MANIFEST_DIR")),
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

/// Runs the embedded Node API CLI. A non-zero child exit is returned as
/// `Ok(Some(code))` — not `process::exit` — so the caller can flush telemetry
/// and honor `--no-fail` before terminating with the same code.
pub fn run(
    args: Vec<String>,
    host_override: Option<String>,
    invocation_context: Option<&InvocationContext>,
) -> Result<Option<i32>, CapturedError> {
    let script = find_script().map_err(|error| CapturedError::from(anyhow::Error::new(error)))?;
    let mut cmd = Command::new("node");
    cmd.arg(script);
    cmd.args(args);
    cmd.env("POSTHOG_CLI_VERSION", env!("CARGO_PKG_VERSION"));
    // Lets the Node script tag its analytics with this invocation, joining them
    // to the Rust-side telemetry for the same run.
    cmd.env("POSTHOG_CLI_INVOCATION_ID", current_invocation_id());

    inject_credentials(&mut cmd, invocation_context);
    inject_analytics_env(&mut cmd);

    if let Some(host) = host_override {
        cmd.env("POSTHOG_CLI_HOST", host);
    }

    let status = cmd.status().map_err(|source| {
        CapturedError::from(anyhow::Error::new(ApiProxyError::NodeSpawnFailed {
            source,
        }))
    })?;

    if status.success() {
        Ok(None)
    } else {
        Ok(Some(status.code().unwrap_or(1)))
    }
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;
    use std::fs;
    use std::sync::Mutex;

    use super::*;

    static POSTHOG_HOME_ENV_LOCK: Mutex<()> = Mutex::new(());

    struct EnvVarGuard {
        name: &'static str,
        previous: Option<OsString>,
    }

    impl EnvVarGuard {
        fn set(name: &'static str, value: &Path) -> Self {
            let previous = env::var_os(name);
            env::set_var(name, value);
            Self { name, previous }
        }
    }

    impl Drop for EnvVarGuard {
        fn drop(&mut self) {
            match &self.previous {
                Some(value) => env::set_var(self.name, value),
                None => env::remove_var(self.name),
            }
        }
    }

    #[test]
    fn legacy_bundle_candidates_include_install_and_development_paths() {
        let install_dir = PathBuf::from("home").join(".posthog");
        let development_dir = PathBuf::from("repo").join("cli");

        let candidates = legacy_bundle_candidates(Some(&install_dir), &development_dir);

        assert_eq!(candidates[0], install_dir.join("lib").join(API_CLI_BUNDLE));
        assert_eq!(
            candidates[1],
            install_dir.join("cli/lib").join(API_CLI_BUNDLE)
        );
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
    fn default_install_dir_honors_posthog_home() {
        let _lock = POSTHOG_HOME_ENV_LOCK.lock().expect("lock POSTHOG_HOME");
        let temp_dir = tempfile::tempdir().expect("create temp dir");
        let _guard = EnvVarGuard::set("POSTHOG_HOME", temp_dir.path());

        assert_eq!(default_install_dir(), Some(temp_dir.path().to_path_buf()));
    }

    #[test]
    fn embedded_bundle_is_materialized_into_a_versioned_install_dir() {
        let temp_dir = tempfile::tempdir().expect("create temp dir");

        let resolved = materialize_embedded_script(Some(b"embedded bundle"), Some(temp_dir.path()))
            .expect("materialize embedded bundle");

        let expected = temp_dir
            .path()
            .join("api-cli")
            .join(env!("CARGO_PKG_VERSION"))
            .join(API_CLI_BUNDLE);
        assert_eq!(
            resolved,
            dunce::canonicalize(&expected).expect("canonicalize materialized bundle")
        );
        assert_eq!(
            fs::read(resolved).expect("read materialized bundle"),
            b"embedded bundle"
        );
    }

    #[test]
    fn embedded_bundle_is_ignored_when_it_was_not_built() {
        let temp_dir = tempfile::tempdir().expect("create temp dir");

        assert!(matches!(
            materialize_embedded_script(None, Some(temp_dir.path())),
            Err(ApiProxyError::BundleNotEmbedded)
        ));
    }

    #[test]
    fn missing_install_dir_reports_home_dir_unavailable() {
        assert!(matches!(
            materialize_embedded_script(Some(b"embedded bundle"), None),
            Err(ApiProxyError::HomeDirUnavailable)
        ));
    }

    #[test]
    fn materialize_failure_reports_step_and_io_error_kind() {
        let temp_dir = tempfile::tempdir().expect("create temp dir");
        // A file where the `api-cli` directory should go makes create_dir_all fail.
        fs::write(temp_dir.path().join("api-cli"), "not a directory").expect("write blocking file");

        let error = materialize_embedded_script(Some(b"embedded bundle"), Some(temp_dir.path()))
            .expect_err("materialization should fail");

        assert!(matches!(
            error,
            ApiProxyError::MaterializeFailed {
                step: MaterializeStep::CreateDir,
                ..
            }
        ));
        assert_eq!(error.telemetry_kind(), "materialize_failed");
        assert_eq!(error.telemetry_step(), Some("create_dir"));
        assert!(error.telemetry_io_error_kind().is_some());
    }

    #[test]
    fn resolve_script_falls_back_to_legacy_bundle_when_embedded_is_missing() {
        let temp_dir = tempfile::tempdir().expect("create temp dir");
        let install_dir = temp_dir.path().join("home").join(".posthog");
        let legacy_bundle = install_dir.join("lib").join(API_CLI_BUNDLE);
        fs::create_dir_all(legacy_bundle.parent().expect("legacy parent"))
            .expect("create legacy lib dir");
        fs::write(&legacy_bundle, "legacy").expect("write legacy bundle");

        let resolved = resolve_script(None, Some(&install_dir), Path::new("/nonexistent-dev-dir"))
            .expect("fall back to legacy bundle");

        assert_eq!(
            resolved,
            dunce::canonicalize(&legacy_bundle).expect("canonicalize legacy")
        );
    }

    #[test]
    fn resolve_script_reports_the_materialize_error_when_no_fallback_exists() {
        let temp_dir = tempfile::tempdir().expect("create temp dir");
        // Block materialization and provide no legacy bundle anywhere.
        fs::write(temp_dir.path().join("api-cli"), "not a directory").expect("write blocking file");

        let error = resolve_script(
            Some(b"embedded bundle"),
            Some(temp_dir.path()),
            Path::new("/nonexistent-dev-dir"),
        )
        .expect_err("resolution should fail");

        assert!(matches!(error, ApiProxyError::MaterializeFailed { .. }));
    }

    #[test]
    fn materialized_embedded_bundle_is_used_before_legacy_install() {
        let temp_dir = tempfile::tempdir().expect("create temp dir");
        let install_dir = temp_dir.path().join("home").join(".posthog");
        let legacy_bundle = install_dir.join("lib").join(API_CLI_BUNDLE);

        fs::create_dir_all(legacy_bundle.parent().expect("legacy parent"))
            .expect("create legacy lib dir");
        fs::write(&legacy_bundle, "legacy").expect("write legacy bundle");

        let resolved = materialize_embedded_script(Some(b"embedded bundle"), Some(&install_dir))
            .expect("materialize embedded bundle");

        assert_eq!(
            resolved,
            dunce::canonicalize(embedded_bundle_path(&install_dir))
                .expect("canonicalize embedded bundle")
        );
        assert_eq!(
            fs::read(resolved).expect("read materialized bundle"),
            b"embedded bundle"
        );
    }
}
