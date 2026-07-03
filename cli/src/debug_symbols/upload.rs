use std::path::PathBuf;

use anyhow::{anyhow, Result};
use tracing::info;

use crate::{
    api::{self, releases::ReleaseBuilder, symbol_sets::SymbolSetUpload},
    debug_symbols::{dedup_uploads_by_chunk_id, discover, package_dsym_bundles, report_problems},
    sourcemaps::args::{pack_version, ReleaseArgs, UploadConflictArgs},
    utils::git::get_git_info,
};

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The directory to scan for native debug symbol files (e.g. target/release).
    /// ELF executables, shared libraries, and `objcopy --only-keep-debug`
    /// companions with debug info are uploaded, as are Apple `.dSYM` bundles
    /// (macOS only — needs `dwarfdump` from Xcode); everything else is skipped.
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
}

pub fn upload(args: &Args) -> Result<()> {
    let Args {
        directory,
        release,
        conflict,
        include_source,
    } = args;
    let release_args = release;

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
        "Found {} ELF debug file(s) and {} dSYM bundle(s)",
        report.files.len(),
        report.dsym_bundles.len()
    );

    // Package everything first, with no release id yet, so we only create a
    // release once we know there's something to upload. dSYM packaging
    // logs-and-skips failures (e.g. a missing dwarfdump), so a dSYM-only
    // directory can yield zero uploads — creating the release up front would
    // leave a release record behind with no symbols attached to it.
    let mut uploads: Vec<SymbolSetUpload> = Vec::new();
    for file in report.files {
        info!(
            "Processing {} (debug id {})",
            file.path.display(),
            file.debug_id
        );
        uploads.push(file.into_upload(None, *include_source)?);
    }

    // Apple dSYM bundles run through the same packaging path as
    // `posthog-cli dsym upload` (uppercase UUID chunk_ids, AppleDsym container);
    // a bundle that can't be processed (e.g. no dwarfdump on Linux) is skipped
    // with a warning so any ELF symbols above still upload.
    uploads.extend(package_dsym_bundles(&report.dsym_bundles, *include_source));

    // ELF (lowercase) and dSYM (uppercase) chunk_ids can't collide, but the same
    // dSYM UUID can appear in more than one bundle — keep one upload per chunk_id.
    let mut uploads = dedup_uploads_by_chunk_id(uploads);

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
    if let Some(release) = created_release {
        let release_id = release.id.to_string();
        for upload in &mut uploads {
            upload.release_id = Some(release_id.clone());
        }
    }

    info!("Uploading {} debug symbol file(s)...", uploads.len());
    // --include-source implies force unless the user explicitly asked to keep
    // existing symbol sets with --skip-on-conflict.
    let effective_force = conflict.force || (*include_source && !conflict.skip_on_conflict);
    api::symbol_sets::upload_with_retry(
        uploads,
        10,
        release_args.skip_release_on_fail,
        effective_force,
        conflict.skip_on_conflict,
    )?;
    info!("Debug symbol upload complete");

    Ok(())
}
