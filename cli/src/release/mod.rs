use std::path::PathBuf;

use anyhow::Result;
use tracing::warn;

use crate::{
    api::releases::Release,
    invocation_context::context,
    sourcemaps::{args::ReleaseArgs, inject::resolve_release},
};

#[derive(clap::Subcommand)]
pub enum ReleaseSubcommand {
    /// Print the id of the release for this build, creating the release if it doesn't exist yet
    Resolve(ResolveArgs),
}

#[derive(clap::Args)]
pub struct ResolveArgs {
    /// The name of the project this release belongs to. Read from git or CI metadata when omitted.
    #[arg(long = "release-name")]
    pub name: Option<String>,

    /// The version of the project: a version number, a semantic version, or a git commit hash.
    /// Read from git or CI metadata when omitted.
    #[arg(long = "release-version")]
    pub version: Option<String>,

    /// The build number (e.g. 42, CFBundleVersion on iOS, versionCode on Android). Packed into the
    /// version, so each build number is a release of its own.
    #[arg(long)]
    pub build: Option<String>,

    /// Read missing release fields from an iOS Info.plist file.
    #[arg(long, value_name = "PATH")]
    pub info_plist: Option<PathBuf>,

    /// Print the whole release as JSON instead of only its id
    #[arg(long, default_value_t = false)]
    pub json: bool,
}

impl From<&ResolveArgs> for ReleaseArgs {
    fn from(args: &ResolveArgs) -> Self {
        Self {
            name: args.name.clone(),
            version: args.version.clone(),
            build: args.build.clone(),
            info_plist: args.info_plist.clone(),
            // Only consulted when a symbol set upload is rejected over its release, and this
            // command uploads nothing.
            skip_release_on_fail: true,
        }
    }
}

pub fn resolve(args: &ResolveArgs) -> Result<()> {
    context().capture_command_invoked("release_resolve");

    let Some(release) = resolve_release(args.into())? else {
        // Exiting zero keeps "this build identifies no release" distinct from a lookup that
        // failed, which exits non-zero. Build tools depend on the difference: the first case
        // still ships a bundle, only without a release id injected into it.
        warn!(
            "No release could be resolved. Pass --release-name and --release-version, or run \
             this from a git repository or a supported CI environment."
        );
        if args.json {
            // Empty stdout is not valid JSON, so emit `null` for a --json consumer to parse.
            println!("null");
        }
        return Ok(());
    };

    println!("{}", render_release(&release, args.json)?);
    Ok(())
}

/// Render the release for stdout: the bare id by default, so `$(posthog-cli release resolve)` is
/// the id itself, and the whole row under `--json` for callers that also want the hash id or the
/// version that git and CI metadata filled in.
fn render_release(release: &Release, json: bool) -> Result<String> {
    if json {
        return Ok(serde_json::to_string_pretty(release)?);
    }
    Ok(release.id.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    const ID: &str = "0e9b3c7a-5d1f-42a8-b6c4-e2d0f8a17593";

    fn release() -> Release {
        Release {
            id: ID.parse().expect("test id is a uuid"),
            hash_id: "e3b0c44298fc1c14".to_string(),
            version: "1.0.0+42".to_string(),
            project: "my-app".to_string(),
        }
    }

    #[test]
    fn plain_output_is_the_id_alone() {
        // Callers pipe stdout straight into an injected snippet, so a label or any other
        // decoration around the id would end up in their bundle.
        assert_eq!(render_release(&release(), false).unwrap(), ID);
    }

    #[test]
    fn json_output_keeps_the_field_names_callers_read() {
        let rendered = render_release(&release(), true).unwrap();

        let parsed: serde_json::Value =
            serde_json::from_str(&rendered).expect("rendered json parses");
        assert_eq!(parsed["id"], ID);
        assert_eq!(parsed["hash_id"], "e3b0c44298fc1c14");
        assert_eq!(parsed["version"], "1.0.0+42");
        assert_eq!(parsed["project"], "my-app");
    }
}
