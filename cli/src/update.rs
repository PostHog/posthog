use std::path::{Path, PathBuf};

use anyhow::{Context, Result};

use crate::safe_println;

// Written by the "Publish artifacts to the release bucket" step in
// release-cli.yml on every stable release: the manifest and both installers are
// republished at these stable keys with a short TTL and a CloudFront
// invalidation, while the versioned artifacts beside them are immutable.
const MANIFEST_URL: &str = "https://releases.posthog.com/posthog-cli/stable/dist-manifest.json";
const INSTALL_SH_URL: &str = "https://releases.posthog.com/posthog-cli/install.sh";
const INSTALL_PS1_URL: &str = "https://releases.posthog.com/posthog-cli/install.ps1";

/// How this copy of posthog-cli got onto the machine.
///
/// Only [`InstallMethod::Script`] owns its own binary. Every other variant is
/// managed by a package manager that would overwrite or fight an in-place
/// update, so those print the command that manager expects instead.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InstallMethod {
    /// Installed by install.sh, which leaves an install receipt. Ours to
    /// replace in place.
    Script,
    /// Installed by install.ps1. Also ours by ownership, but Windows will not
    /// let the installer overwrite the executable that is running it, so the
    /// user has to run the installer themselves.
    ScriptWindows,
    Homebrew,
    /// Anything under a node_modules: a global install, a project dependency,
    /// one pulled in by a plugin or SDK, or an npx cache. npm owns the file in
    /// every case, so they get one message. The path is carried because it is
    /// the part that tells someone which copy they just ran.
    Npm(PathBuf),
    Cargo,
    Unknown,
}

/// What to tell someone whose install we do not own.
pub enum Guidance {
    /// Run this command.
    Command(String),
    /// No single command applies; explain instead.
    Explain(String),
}

impl InstallMethod {
    /// How this install updates, or None when we own it and can do it here.
    pub fn guidance(&self) -> Option<Guidance> {
        match self {
            InstallMethod::Script => None,
            // install.ps1 places binaries with `Copy-Item` straight over the
            // destination, and Windows refuses that while the file is mapped
            // into a running process. Running it from a shell works, because
            // posthog-cli is not running then.
            InstallMethod::ScriptWindows => {
                Some(Guidance::Command(format!("irm {INSTALL_PS1_URL} | iex")))
            }
            InstallMethod::Homebrew => Some(Guidance::Command("brew upgrade posthog-cli".into())),
            InstallMethod::Cargo => Some(Guidance::Command(
                "cargo install posthog-cli --force".into(),
            )),
            InstallMethod::Npm(path) => Some(Guidance::Explain(format!(
                "this copy is managed by npm, at\n\n    {}\n\n\
                 Update it through npm rather than here.",
                path.display()
            ))),
            InstallMethod::Unknown => Some(Guidance::Command(
                "curl -LsSf https://releases.posthog.com/posthog-cli/install.sh | sh".into(),
            )),
        }
    }
}

/// The prefix the install script recorded as this install's home, if a receipt
/// exists and names one.
///
/// Presence of a receipt is not enough on its own. It describes whatever the
/// script installed last, which may be a different binary from the one running:
/// a developer's debug build, or a copy since replaced by a package manager.
/// Updating on that basis runs the installer over an install the caller is not
/// using.
fn receipt_install_prefix() -> Option<PathBuf> {
    let raw = std::fs::read_to_string(receipt_path()?).ok()?;
    let receipt: serde_json::Value = serde_json::from_str(&raw).ok()?;
    receipt["install_prefix"].as_str().map(PathBuf::from)
}

/// Where the install receipt lives, following the same search order the
/// generated installer writes it in.
fn receipt_path() -> Option<PathBuf> {
    // Both generated installers try XDG_CONFIG_HOME first. install.ps1 falls
    // back to LOCALAPPDATA, install.sh to ~/.config. Checking only LOCALAPPDATA
    // on Windows would miss a script install made with XDG_CONFIG_HOME set.
    let home = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| {
            if cfg!(windows) {
                std::env::var_os("LOCALAPPDATA").map(PathBuf::from)
            } else {
                dirs::home_dir().map(|h| h.join(".config"))
            }
        })?;
    Some(home.join("posthog-cli").join("posthog-cli-receipt.json"))
}

/// Classify this binary by where it actually lives on disk.
///
/// Path wins over the receipt on purpose. A machine can carry several installs
/// at once, and a receipt left by an earlier install.sh run says nothing about
/// the binary currently executing. Trusting it first would "update" a copy that
/// is not the one on PATH, and report success having changed nothing.
pub fn detect_install_method() -> InstallMethod {
    // The rule guards against trusting current_exe for a security decision.
    // This one is not: it picks which message to print, and whether to run the
    // official installer over the caller's own install. A caller who forges the
    // path gets their own CLI reinstalled from releases.posthog.com, which is
    // what the command does anyway. No privilege boundary and no other user is
    // involved.
    // nosemgrep: rust.lang.security.current-exe.current-exe
    let Ok(exe) = std::env::current_exe() else {
        return InstallMethod::Unknown;
    };
    // canonicalize, not read_link: Homebrew's symlinks are relative
    // (../Cellar/...), so a single read_link never matches an absolute prefix.
    let resolved = std::fs::canonicalize(&exe).unwrap_or(exe);
    // Owned by the script only when the receipt's prefix actually contains this
    // binary, so a receipt left by another install cannot claim it.
    let owned_by_script = receipt_install_prefix()
        .and_then(|prefix| std::fs::canonicalize(prefix).ok())
        .is_some_and(|prefix| resolved.starts_with(prefix));
    classify_path(&resolved, owned_by_script)
}

fn classify_path(resolved: &Path, owned_by_script: bool) -> InstallMethod {
    let has = |needle: &str| {
        resolved
            .components()
            .any(|c| c.as_os_str().to_string_lossy() == needle)
    };

    if has("Cellar") {
        return InstallMethod::Homebrew;
    }
    // The npm bin entry is a JS shim, so every npm case resolves to
    // run-posthog-cli.js inside node_modules rather than to a binary. Which
    // node_modules it is decides what the user should do about it.
    // Global, project dependency, plugin or SDK dependency, and npx cache all
    // land here. Telling them apart was tried and dropped: the layouts differ
    // per platform and per package manager, and npm owns the file either way,
    // so a wrong guess would send someone to the wrong copy.
    if has("node_modules") {
        return InstallMethod::Npm(resolved.to_path_buf());
    }
    if resolved
        .parent()
        .is_some_and(|p| p.ends_with(Path::new(".cargo").join("bin")))
    {
        return InstallMethod::Cargo;
    }
    if owned_by_script {
        return if cfg!(windows) {
            InstallMethod::ScriptWindows
        } else {
            InstallMethod::Script
        };
    }
    InstallMethod::Unknown
}

fn latest_version() -> Result<String> {
    let manifest: serde_json::Value = reqwest::blocking::Client::new()
        .get(MANIFEST_URL)
        .send()
        .context("Failed to reach releases.posthog.com")?
        .error_for_status()
        .context("The release manifest is unavailable")?
        .json()
        .context("The release manifest could not be parsed")?;

    manifest["releases"][0]["app_version"]
        .as_str()
        .map(str::to_owned)
        .context("The release manifest carries no version")
}

fn run_installer(prefix: &Path) -> Result<()> {
    let body = reqwest::blocking::Client::new()
        .get(INSTALL_SH_URL)
        .send()
        .context("Failed to download the installer")?
        .error_for_status()
        .context("The installer is unavailable")?
        .text()
        .context("The installer could not be read")?;

    let dir = tempfile::tempdir().context("Failed to create a temporary directory")?;
    let script = dir.path().join("install.sh");
    std::fs::write(&script, body).context("Failed to write the installer")?;

    // Without this the installer writes to its own default, so an install in a
    // custom directory would be left untouched while a second copy appeared in
    // ~/.posthog and the command reported success.
    let status = std::process::Command::new("sh")
        .arg(&script)
        .env("POSTHOG_CLI_INSTALL_DIR", prefix)
        .status()
        .context("Failed to run the installer")?;

    anyhow::ensure!(status.success(), "The installer exited with {status}");
    Ok(())
}

/// Delete a `posthog-cli-update` binary sitting next to the CLI.
///
/// That binary resolves versions through the GitHub releases API, which cannot
/// reach a CLI release in this monorepo, so it is non-functional. On PATH it
/// still looks like the way to update.
///
/// Bounded deliberately: one exact filename, only inside the prefix the receipt
/// says we own, and a failure to remove is not worth failing the update over.
fn remove_stale_standalone_updater(prefix: &Path) {
    let name = "posthog-cli-update";
    let path = prefix.join(name);
    if path.is_file() && std::fs::remove_file(&path).is_ok() {
        safe_println!("Removed the old {name}, which no longer works.");
    }
}

pub fn update() -> Result<()> {
    let method = detect_install_method();

    match method.guidance() {
        Some(Guidance::Command(command)) => {
            safe_println!(
                "posthog-cli was not installed by the install script, so it updates with:"
            );
            safe_println!();
            safe_println!("    {command}");
            return Ok(());
        }
        Some(Guidance::Explain(text)) => {
            safe_println!("posthog-cli was not installed by the install script: {text}");
            return Ok(());
        }
        None => {}
    }

    let current = env!("CARGO_PKG_VERSION");
    let latest = latest_version()?;
    if latest == current {
        safe_println!("posthog-cli {current} is already the latest version.");
        return Ok(());
    }

    let prefix = receipt_install_prefix()
        .context("The install receipt names no install_prefix, so there is nowhere to install")?;

    safe_println!("Updating posthog-cli {current} to {latest}.");
    run_installer(&prefix)?;
    remove_stale_standalone_updater(&prefix);
    safe_println!("posthog-cli is now {latest}.");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_install_layouts() {
        // Paths measured on a machine carrying several installs at once.
        // The flag is varied because it is the other input. It means "the
        // receipt's install_prefix contains this binary", not "a receipt
        // exists", so a debug build or a package-manager copy cannot be claimed
        // by a receipt left behind by an earlier install.sh run.
        let npm_plugin =
            "/w/app/node_modules/@posthog/vite-plugin/node_modules/@posthog/cli/run-posthog-cli.js";
        let cases: &[(&str, bool, InstallMethod)] = &[
            // Homebrew symlinks are relative, so this is what breaks if
            // canonicalize is ever swapped back to read_link.
            (
                "/opt/homebrew/Cellar/posthog-cli/0.18.5/bin/posthog-cli",
                true,
                InstallMethod::Homebrew,
            ),
            (
                "/usr/local/Cellar/posthog-cli/0.18.5/bin/posthog-cli",
                false,
                InstallMethod::Homebrew,
            ),
            // Global, npx cache and a plugin's nested copy are all npm's to
            // update. Re-splitting them on a path heuristic would send the last
            // two to a copy they never ran.
            (
                "/Users/x/.nvm/versions/node/v26.2.0/lib/node_modules/@posthog/cli/run-posthog-cli.js",
                true,
                InstallMethod::Npm(PathBuf::from(
                    "/Users/x/.nvm/versions/node/v26.2.0/lib/node_modules/@posthog/cli/run-posthog-cli.js",
                )),
            ),
            (
                "/Users/x/.npm/_npx/6d80974bf710451e/node_modules/@posthog/cli/run-posthog-cli.js",
                true,
                InstallMethod::Npm(PathBuf::from(
                    "/Users/x/.npm/_npx/6d80974bf710451e/node_modules/@posthog/cli/run-posthog-cli.js",
                )),
            ),
            (npm_plugin, true, InstallMethod::Npm(PathBuf::from(npm_plugin))),
            ("/Users/x/.cargo/bin/posthog-cli", true, InstallMethod::Cargo),
            // Only a binary living under the receipt's own prefix is ours to
            // update in place.
            (
                "/Users/x/.posthog/posthog-cli",
                true,
                InstallMethod::Script,
            ),
            (
                "/Users/x/.posthog/posthog-cli",
                false,
                InstallMethod::Unknown,
            ),
        ];

        for (path, owned, expected) in cases {
            assert_eq!(
                classify_path(Path::new(path), *owned),
                *expected,
                "{path} (owned: {owned})"
            );
        }
    }

    #[test]
    fn only_a_script_install_updates_itself() {
        assert!(InstallMethod::Script.guidance().is_none());
        for method in [
            // Owned by us, but Windows cannot replace a running executable, so
            // it still has to hand the user a command.
            InstallMethod::ScriptWindows,
            InstallMethod::Homebrew,
            InstallMethod::Npm(PathBuf::from("/w/app/node_modules/x")),
            InstallMethod::Cargo,
            InstallMethod::Unknown,
        ] {
            assert!(method.guidance().is_some(), "{method:?}");
        }
    }
}
