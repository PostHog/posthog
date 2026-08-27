use std::path::PathBuf;

use anyhow::{anyhow, Result};
use tracing::info;

use crate::{
    api::{
        self,
        releases::ReleaseBuilder,
        symbol_sets::{dedup_uploads_by_chunk_id, SymbolSetUpload, MAX_FILE_SIZE},
    },
    debug_symbols::{discover, package_dsym_bundles, report_problems},
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

    /// How the release is associated with exceptions. `symbol-set`, the default, resolves a release
    /// (from the flags above or git) and binds it to every uploaded symbol set, so an exception
    /// takes the release of the symbol sets its frames resolved against. EXPERIMENTAL `event`
    /// instead uploads new symbol sets release-independent (an already-bound symbol set keeps its
    /// release): each exception carries the release as `$release_id`, which the SDK reports from
    /// `POSTHOG_RELEASE_ID` (posthog-rs 0.26+). So one
    /// symbol set serves every release of an unchanged binary, and the release flags are not needed
    /// here — name the release with `posthog-cli release resolve` instead. Also settable via
    /// `POSTHOG_RELEASE_MODE`.
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
        directory,
        release,
        conflict,
        include_source,
        release_mode,
    } = args;

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

    match release_mode {
        // Resolve a release (explicit flags win, git info is metadata/fallback) and stamp it on
        // every set, so an exception takes the release of the symbol sets it resolves against.
        ReleaseMode::SymbolSet => {
            // Only this mode reads release metadata, so resolve the Info.plist here rather than up
            // front — an event-mode upload never uses it and must not abort on a bad --info-plist.
            let release_args = release.resolve_info_plist()?;
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
            if let Some(release) = created_release {
                let release_id = release.id.to_string();
                for upload in &mut uploads {
                    upload.release_id = Some(release_id.clone());
                }
            }
        }
        // Upload the symbol sets release-independent (bound to no release). The release rides the
        // event instead: the SDK reports it as `$release_id` (from `POSTHOG_RELEASE_ID`), and the
        // server resolves each exception by that id. One symbol set then serves every release of an
        // unchanged binary, so there is nothing to resolve or bind here.
        ReleaseMode::Event => {
            info!(
                "--release-mode=event: uploading symbol sets release-independent; the release is \
                 carried on each exception as $release_id (POSTHOG_RELEASE_ID)"
            );
        }
    }

    info!("Uploading {} debug symbol file(s)...", uploads.len());
    // --include-source implies force unless the user explicitly asked to keep
    // existing symbol sets with --skip-on-conflict.
    let effective_force = conflict.force || (*include_source && !conflict.skip_on_conflict);
    let (_summary, upload_result) = api::symbol_sets::upload_with_retry(
        uploads,
        10,
        release.skip_release_on_fail,
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
        // Every existing caller omits the flag and must keep binding symbol sets to their release.
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
