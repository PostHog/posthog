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

    /// How the release is associated with exceptions. `symbol-set`, the default, stamps the
    /// release id onto the uploaded mapping, and an exception takes the release of the mappings
    /// its frames resolved against. EXPERIMENTAL `event` leaves the mapping
    /// release-independent, and each event resolves its own release from the app version and
    /// namespace the SDK already sends, so the release coordinates have to match the app's. The
    /// release is created either way. Also settable via `POSTHOG_RELEASE_MODE`.
    #[arg(
        long,
        env = "POSTHOG_RELEASE_MODE",
        value_enum,
        default_value = "symbol-set"
    )]
    pub release_mode: ReleaseMode,
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

    let resolved_release = release.resolve_info_plist()?;
    let ReleaseArgs {
        name,
        version,
        build,
        info_plist: _,
        skip_release_on_fail,
    } = &resolved_release;

    // Event mode leaves nothing on the symbol set for the server to fall back to, so an
    // exception resolves its release only from the app metadata on the event itself. Coordinates
    // derived from git rather than passed explicitly will not match that metadata, and the
    // exception then reports no release at all, silently.
    if *release_mode == ReleaseMode::Event && (name.is_none() || version.is_none()) {
        warn!(
            "--release-mode=event resolves each exception's release from the app's namespace and \
             version. Pass --release-name, --release-version and --build matching the app's \
             applicationId, versionName and versionCode, or exceptions will report no release."
        );
    }

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

    // The release is created in both modes, so the server has a row to resolve an event's
    // `$app_namespace` / `$app_version` / `$app_build` onto. Event mode only skips binding it to
    // the mapping: a map id is derived from the mapping's own content, so the same mapping keeps
    // one symbol set across releases instead of colliding with the release the first upload
    // stamped on it.
    //
    // Unlike sourcemaps, event mode does not imply `--force` here. The uploaded bytes are the
    // mapping itself, with no injected release id, so a rebuild of unchanged code produces
    // identical content under the same id and never conflicts. A conflict means the caller reused
    // a `--map-id` for a different mapping, which is worth reporting in either mode.
    file.release_id = match release_mode {
        ReleaseMode::Event => None,
        ReleaseMode::SymbolSet => release.map(|r| r.id.to_string()),
    };

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
    use clap::Parser;

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
    fn defaults_to_binding_the_release_to_the_mapping() {
        // Every existing caller omits the flag, and they must keep uploading mappings stamped with
        // their release.
        assert_eq!(parse(&[]).release_mode, ReleaseMode::SymbolSet);
    }

    #[test]
    fn accepts_event_release_mode() {
        assert_eq!(
            parse(&["--release-mode", "event"]).release_mode,
            ReleaseMode::Event
        );
    }
}
