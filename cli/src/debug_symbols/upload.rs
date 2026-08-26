use std::path::PathBuf;

use anyhow::{anyhow, Result};
use tracing::{info, warn};

use crate::{
    api::{
        self,
        releases::ReleaseBuilder,
        symbol_sets::{dedup_uploads_by_chunk_id, SymbolSetUpload, MAX_FILE_SIZE},
    },
    debug_symbols::{discover, package_dsym_bundles, report_problems},
    release_injection::inject_release_id,
    sourcemaps::args::{pack_version, ReleaseArgs, ReleaseMode, UploadConflictArgs},
    utils::git::get_git_info,
};

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The directory to scan for native debug symbol files (e.g. target/release).
    /// ELF and Mach-O executables, shared libraries, and `objcopy
    /// --only-keep-debug` companions with debug info are uploaded, as are Apple
    /// `.dSYM` bundles (macOS only — needs `dwarfdump` from Xcode); everything
    /// else is skipped.
    #[arg(short, long)]
    pub directory: PathBuf,

    #[clap(flatten)]
    pub release: ReleaseArgs,

    #[clap(flatten)]
    pub conflict: UploadConflictArgs,

    /// Include source code files in the upload.
    /// When enabled, project source files referenced by DWARF debug info are
    /// bundled in, allowing PostHog to display source context around frames.
    /// Implies --force unless --skip-on-conflict is set.
    #[arg(long, default_value_t = false)]
    pub include_source: bool,

    /// How the release is associated with exceptions. `symbol-set`, the default, stamps the release
    /// id onto every uploaded symbol set. EXPERIMENTAL `event` instead injects the created release's
    /// id into the binary, where the SDK reads it and reports it as `$release_id`; the symbol sets
    /// stay release-independent. Needs an SDK that compiles the marker in (posthog-rs 0.26+). Also
    /// settable via `POSTHOG_RELEASE_MODE`.
    #[arg(
        long,
        env = "POSTHOG_RELEASE_MODE",
        value_enum,
        default_value = "symbol-set"
    )]
    pub release_mode: ReleaseMode,

    /// With `--release-mode=event`, skip re-signing the binary ad-hoc after injecting the release
    /// id. Injecting invalidates the Mach-O code signature, so the binary must be re-signed before
    /// it runs on macOS; by default the CLI re-signs ad-hoc. Pass this when your pipeline signs the
    /// binary itself after upload (e.g. a notarized build), so its real signature is not replaced.
    #[arg(long, default_value_t = false)]
    pub no_resign: bool,
}

pub fn upload(args: &Args) -> Result<()> {
    let Args {
        directory,
        release,
        conflict,
        include_source,
        release_mode,
        no_resign,
    } = args;
    let release_args = release.resolve_info_plist()?;

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Path {} canonicalization failed: {}",
            directory.display(),
            e
        )
    })?;

    if !directory.is_dir() {
        anyhow::bail!("Path {} is not a directory", directory.display());
    }

    let report = discover(&directory)?;
    report_problems(&report, &directory)?;

    info!(
        "Found {} native debug file(s) and {} dSYM bundle(s)",
        report.files.len(),
        report.dsym_bundles.len()
    );

    // Package everything first, with no release id yet, so we only create a
    // release once we know there's something to upload. dSYM packaging
    // logs-and-skips failures (e.g. a missing dwarfdump), so a dSYM-only
    // directory can yield zero uploads — creating the release up front would
    // leave a release record behind with no symbols attached to it.
    let mut native_uploads = Vec::with_capacity(report.files.len());
    for file in report.files {
        info!(
            "Processing {} (debug id {})",
            file.path.display(),
            file.debug_id
        );
        native_uploads.push(file.into_upload(None, *include_source)?);
    }

    // A failed or oversized dSYM leaves a matching standalone Mach-O as the
    // fallback. Successfully packaged, uploadable dSYMs take priority.
    let dsym_uploads = package_dsym_bundles(&report.dsym_bundles, *include_source);
    let mut uploads = merge_uploads_prefer_dsym(dsym_uploads, native_uploads, MAX_FILE_SIZE);

    if uploads.is_empty() {
        anyhow::bail!(
            "No debug symbols could be packaged for upload from {}",
            directory.display()
        );
    }

    // Now that there's something to upload, set up the release (explicit flags
    // win, git info is metadata/fallback) and stamp it on every set.
    let mut release_builder = ReleaseBuilder::default();
    if let Ok(Some(git_info)) = get_git_info(Some(directory.clone())) {
        release_builder.with_git(git_info);
    }
    if let Some(ref release_name) = release_args.name {
        release_builder.with_name(release_name);
    }
    if let Some(version) = pack_version(&release_args.version, &release_args.build) {
        release_builder.with_version(&version);
    }

    let created_release = release_builder
        .can_create()
        .then(|| release_builder.fetch_or_create())
        .transpose()?;

    match release_mode {
        // Bind the release to every uploaded symbol set (the previous behavior).
        ReleaseMode::SymbolSet => {
            if let Some(release) = created_release {
                let release_id = release.id.to_string();
                for upload in &mut uploads {
                    upload.release_id = Some(release_id.clone());
                }
            }
        }
        // Carry the release on the event, not the symbol set: inject the created release's id into
        // the binary (the SDK reports it as `$release_id`) and leave the symbol sets
        // release-independent. Resolution is by the id, so nothing has to match the app.
        ReleaseMode::Event => match created_release {
            Some(release) => {
                let release_id = release.id.to_string();
                let patched = inject_release_id(&directory, &release_id, !*no_resign)?;
                if patched == 0 {
                    warn!(
                        "--release-mode=event created release {release_id}, but found no PostHog \
                         release marker under {} to inject it into, so exceptions will report no \
                         release. Link an SDK that supports release injection (posthog-rs 0.26+) \
                         and point --directory at that build's output.",
                        directory.display()
                    );
                } else {
                    info!(
                        "Injected release {release_id} into {patched} binary/binaries; symbol sets upload release-independent"
                    );
                }
            }
            None => warn!(
                "--release-mode=event needs a release to inject into the binary, but none could \
                 be resolved. Pass --release-name and --release-version, or run from a git \
                 repository, or exceptions will report no release."
            ),
        },
    }

    info!("Uploading {} debug symbol file(s)...", uploads.len());
    // --include-source implies force unless --skip-on-conflict. Event mode implies it too: on Linux
    // the marker lives in the same ELF we upload as symbols, so re-injecting a new id changes the
    // uploaded content under an unchanged build id — force lets a re-release overwrite it. (On
    // macOS the symbols are a separate dSYM, so this is moot.)
    let effective_force = conflict.force
        || (*include_source && !conflict.skip_on_conflict)
        || (*release_mode == ReleaseMode::Event && !conflict.skip_on_conflict);
    let (_summary, upload_result) = api::symbol_sets::upload_with_retry(
        uploads,
        10,
        release_args.skip_release_on_fail,
        effective_force,
        conflict.skip_on_conflict,
    );
    upload_result?;
    info!("Debug symbol upload complete");

    Ok(())
}

/// Merge packaged native symbols, preferring an uploadable dSYM when both
/// inputs carry the same uppercase Mach-O UUID. Oversized dSYMs come last so a
/// matching native upload wins, but remain available when there is no fallback
/// and the upload layer can preserve its existing warning behavior. ELF ids
/// remain lowercase and cannot collide.
fn merge_uploads_prefer_dsym(
    dsym_uploads: Vec<SymbolSetUpload>,
    native_uploads: Vec<SymbolSetUpload>,
    max_file_size: usize,
) -> Vec<SymbolSetUpload> {
    let (mut preferred_dsyms, oversized_dsyms): (Vec<_>, Vec<_>) = dsym_uploads
        .into_iter()
        .partition(|upload| upload.data.len() <= max_file_size);
    preferred_dsyms.extend(native_uploads);
    preferred_dsyms.extend(oversized_dsyms);
    // Casing must never be normalized here: the SDK matches chunk_ids case-sensitively, per
    // format, and lowercase ELF ids never collide with uppercase Mach-O ones.
    dedup_uploads_by_chunk_id(preferred_dsyms)
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    #[derive(Parser)]
    struct SymbolSetsCli {
        #[command(subcommand)]
        command: crate::download::SymbolSetsSubcommand,
    }

    fn parse_upload(extra: &[&str]) -> Args {
        let mut argv = vec!["symbol-sets", "upload", "--directory", "target/release"];
        argv.extend_from_slice(extra);
        match SymbolSetsCli::parse_from(argv).command {
            crate::download::SymbolSetsSubcommand::Upload(args) => args,
            _ => panic!("expected the upload subcommand"),
        }
    }

    #[test]
    fn defaults_to_binding_the_release_to_the_symbol_sets() {
        // Every existing caller omits the flag and must keep uploading symbol sets stamped with
        // their release. A different default would silently unbind all of them.
        assert_eq!(parse_upload(&[]).release_mode, ReleaseMode::SymbolSet);
    }

    #[test]
    fn accepts_event_release_mode() {
        assert_eq!(
            parse_upload(&["--release-mode", "event"]).release_mode,
            ReleaseMode::Event
        );
    }

    #[test]
    fn resigns_by_default_and_no_resign_opts_out() {
        assert!(!parse_upload(&[]).no_resign);
        assert!(parse_upload(&["--no-resign"]).no_resign);
    }

    #[test]
    fn merge_uploads_prefers_dsym_over_matching_macho() {
        let uuid = "77C2F55F-C959-487A-9601-6A715A9BB5DE";
        let upload = |chunk_id: &str, data: &[u8]| SymbolSetUpload {
            chunk_id: chunk_id.to_string(),
            release_id: None,
            data: data.to_vec(),
            content_hash: None,
        };

        let uploads = merge_uploads_prefer_dsym(
            vec![upload(uuid, b"dsym")],
            vec![upload(uuid, b"macho")],
            10,
        );

        assert_eq!(uploads.len(), 1);
        assert_eq!(uploads[0].data, b"dsym");
    }

    #[test]
    fn merge_uploads_uses_macho_when_matching_dsym_is_oversized() {
        let uuid = "77C2F55F-C959-487A-9601-6A715A9BB5DE";
        let upload = |data: &[u8]| SymbolSetUpload {
            chunk_id: uuid.to_string(),
            release_id: None,
            data: data.to_vec(),
            content_hash: None,
        };

        let uploads =
            merge_uploads_prefer_dsym(vec![upload(b"oversized-dsym")], vec![upload(b"macho")], 5);

        assert_eq!(uploads.len(), 1);
        assert_eq!(uploads[0].data, b"macho");
    }
}
