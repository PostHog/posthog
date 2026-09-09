use std::path::PathBuf;

use anyhow::{anyhow, Result};
use tracing::warn;

use crate::{
    api::{self, releases::ReleaseBuilder, symbol_sets::SymbolSetUpload},
    proguard::ProguardFile,
    sourcemaps::args::{pack_version, ReleaseArgs, ReleaseMode, UploadConflictArgs},
    utils::git::get_git_info,
};

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The location of the proguard mapping file to upload.
    #[arg(short, long)]
    pub path: PathBuf,

    /// The identifier PostHog uses to look up this mapping file when processing your stack traces.
    /// Must match the identifier provided to the PostHog SDK at runtime for this build.
    #[arg(short, long)]
    pub map_id: String,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,

    #[clap(flatten)]
    pub release: ReleaseArgs,

    #[clap(flatten)]
    pub conflict: UploadConflictArgs,

    /// Deprecated: the mapping always binds to the release the build creates. The flag stays
    /// accepted so a gradle plugin that still passes it does not fail to parse, and it no longer
    /// reads `POSTHOG_RELEASE_MODE`, which keeps steering the sourcemap and hermes commands.
    #[arg(long, value_enum, hide = true)]
    pub release_mode: Option<ReleaseMode>,
}

pub fn upload(args: &Args) -> Result<()> {
    let Args {
        path,
        map_id,
        batch_size,
        release,
        conflict,
        release_mode,
    } = args;

    if release_mode.is_some() {
        warn!(
            "--release-mode is deprecated and does nothing. The mapping is uploaded bound to the \
             release this build creates. Remove the flag."
        );
    }

    let resolved_release = release.resolve_info_plist()?;
    let ReleaseArgs {
        name,
        version,
        build,
        info_plist: _,
        skip_release_on_fail,
    } = &resolved_release;

    let path = path
        .canonicalize()
        .map_err(|e| anyhow!("Path {} canonicalization failed: {}", path.display(), e))?;
    let directory = path
        .parent()
        .ok_or_else(|| anyhow!("Could not get path parent"))?;

    let mut release_builder = get_git_info(Some(directory.to_path_buf()))?
        .map(ReleaseBuilder::init_from_git)
        .unwrap_or_default();

    if let Some(name) = name {
        release_builder.with_name(name);
    }
    let full_version = pack_version(version, build);
    if let Some(ref v) = full_version {
        release_builder.with_version(v);
    }

    let mut file = ProguardFile::new(&path, map_id.clone())?;

    let release = release_builder
        .can_create()
        .then(|| release_builder.fetch_or_create())
        .transpose()?;

    // Bind the mapping to the release this build resolved, so an exception symbolicated with this
    // mapping takes that release. A build with no release name or version resolves none, and the
    // upload then carries no release id. `--skip-release-on-fail` can also drop the binding when
    // the server rejects it.
    file.release_id = release.map(|r| r.id.to_string());

    let to_upload: SymbolSetUpload = file.try_into()?;

    let (_summary, upload_result) = api::symbol_sets::upload_with_retry(
        vec![to_upload],
        *batch_size,
        *skip_release_on_fail,
        conflict.force,
        conflict.skip_on_conflict,
    );
    upload_result?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::{CommandFactory, Parser};

    #[derive(Parser)]
    struct ProguardCli {
        #[command(subcommand)]
        command: crate::proguard::ProguardSubcommand,
    }

    fn parse(extra: &[&str]) -> Args {
        let mut argv = vec![
            "proguard",
            "upload",
            "--path",
            "mapping.txt",
            "--map-id",
            "id",
        ];
        argv.extend_from_slice(extra);
        let crate::proguard::ProguardSubcommand::Upload(args) =
            ProguardCli::parse_from(argv).command;
        args
    }

    #[test]
    fn accepts_the_deprecated_release_mode_flag() {
        // Released gradle plugins pass `--release-mode event`. Rejecting the flag would fail
        // their builds with a parse error on CLI upgrade.
        assert_eq!(
            parse(&["--release-mode", "event"]).release_mode,
            Some(ReleaseMode::Event)
        );
        assert_eq!(
            parse(&["--release-mode", "symbol-set"]).release_mode,
            Some(ReleaseMode::SymbolSet)
        );
        assert_eq!(parse(&[]).release_mode, None);
    }

    #[test]
    fn deprecated_release_mode_is_hidden_and_reads_no_environment() {
        // A default or an env binding would mark unconfigured runs as deprecated callers, and
        // POSTHOG_RELEASE_MODE stays a real control for the sourcemap and hermes commands.
        let cmd = ProguardCli::command();
        let upload = cmd
            .find_subcommand("upload")
            .expect("expected the upload subcommand");
        let arg = upload
            .get_arguments()
            .find(|a| a.get_id() == "release_mode")
            .expect("expected the release_mode argument");

        assert!(arg.is_hide_set());
        assert!(arg.get_env().is_none());
    }
}
