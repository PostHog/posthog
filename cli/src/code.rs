use std::process::Command;

use anyhow::{Context, Result};

/// The npm package that carries the TUI. `npx` fetches the newest release on each start, so a
/// `posthog-cli` build never pins a TUI version it would then have to re-release to bump.
const TUI_PACKAGE: &str = "@posthog/tui";

/// The arguments `npx` runs the TUI with: the latest package, taken without a prompt, then whatever
/// the user passed through.
pub fn npx_args(passthrough: &[String]) -> Vec<String> {
    let mut args = vec!["-y".to_string(), format!("{TUI_PACKAGE}@latest")];
    args.extend(passthrough.iter().cloned());
    args
}

/// Starts the TUI in the current folder and waits for it, returning its exit code.
pub fn code(passthrough: Vec<String>) -> Result<Option<i32>> {
    let status = Command::new("npx")
        .args(npx_args(&passthrough))
        .status()
        .context(
            "Failed to execute `npx`. The `code` command needs Node.js 22.19 or newer on PATH.",
        )?;
    Ok(if status.success() {
        None
    } else {
        Some(status.code().unwrap_or(1))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runs_the_latest_tui_without_a_prompt_and_passes_arguments_through() {
        assert_eq!(
            npx_args(&["--version".to_string()]),
            vec!["-y", "@posthog/tui@latest", "--version"]
        );
        assert_eq!(npx_args(&[]), vec!["-y", "@posthog/tui@latest"]);
    }
}
