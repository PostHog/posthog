/// Delegates `posthog-cli api <args...>` to the Node-based API CLI.
///
/// Locates the bundled JS entry point and execs it via `node`, passing through
/// all arguments, env vars, and stdio. Auth credentials from `posthog-cli login`
/// (stored in ~/.posthog/credentials.json) are injected as env vars so the Node
/// CLI picks them up without needing its own file-based auth.
///
/// Resolution order for the script:
/// 1. `PH_API_CLI_PATH` env var (explicit override)
/// 2. `../lib/api-cli/index.js` relative to binary (npm package layout)
/// 3. Monorepo: `services/agent-cli/src/index.ts` via `tsx` (dev)
use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{bail, Context, Result};

use crate::error::CapturedError;
use crate::utils::auth::{get_token, Token};

fn find_script() -> Result<(String, Vec<String>)> {
    // 1. Explicit override
    if let Ok(path) = env::var("PH_API_CLI_PATH") {
        if Path::new(&path).exists() {
            return Ok(("node".into(), vec![path]));
        }
    }

    // 2. Bundled alongside the binary (production npm package)
    if let Ok(exe) = env::current_exe() {
        if let Some(bin_dir) = exe.parent() {
            let bundled = bin_dir.join("../lib/api-cli/index.js");
            if bundled.exists() {
                let canonical = bundled.canonicalize()?;
                return Ok(("node".into(), vec![canonical.display().to_string()]));
            }
        }
    }

    // 3. Monorepo dev — walk up from cwd to find repo root, then use tsx
    if let Some(repo_root) = find_repo_root() {
        let src = repo_root.join("services/agent-cli/src/index.ts");
        if src.exists() {
            let tsx = find_tsx(&repo_root)?;
            return Ok((tsx, vec![src.display().to_string()]));
        }
    }

    bail!(
        "Could not find the API CLI script.\n\
         Set PH_API_CLI_PATH or run from within the PostHog monorepo.\n\
         Install: npm install -g @posthog/cli"
    )
}

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

fn find_tsx(repo_root: &Path) -> Result<String> {
    let candidates = [
        repo_root.join("services/agent-cli/node_modules/.bin/tsx"),
        repo_root.join("node_modules/.bin/tsx"),
    ];
    for candidate in &candidates {
        if candidate.exists() {
            return Ok(candidate.display().to_string());
        }
    }
    Ok("tsx".into())
}

fn inject_credentials(cmd: &mut Command) {
    // Only inject if the user hasn't already set env vars (don't override explicit config)
    if env::var("POSTHOG_CLI_API_KEY").is_ok() || env::var("POSTHOG_API_KEY").is_ok() {
        return;
    }

    if let Ok(Token {
        token,
        env_id,
        host,
    }) = get_token()
    {
        cmd.env("POSTHOG_CLI_API_KEY", token);
        cmd.env("POSTHOG_CLI_PROJECT_ID", env_id);
        if let Some(h) = host {
            cmd.env("POSTHOG_CLI_HOST", h);
        }
    }
}

pub fn run(args: Vec<String>, host_override: Option<String>) -> Result<(), CapturedError> {
    let (program, script_args) = find_script().map_err(CapturedError::from)?;

    let mut cmd = Command::new(&program);
    cmd.args(&script_args);
    cmd.args(&args);

    cmd.env("PH_CLI_PREFIX", "posthog-cli api");

    inject_credentials(&mut cmd);

    // --host flag takes precedence over everything
    if let Some(host) = host_override {
        cmd.env("POSTHOG_CLI_HOST", host);
    }

    let status = cmd
        .status()
        .with_context(|| format!("Failed to execute `{program}`. Is Node.js installed?"))
        .map_err(CapturedError::from)?;

    if !status.success() {
        std::process::exit(status.code().unwrap_or(1));
    }

    Ok(())
}
