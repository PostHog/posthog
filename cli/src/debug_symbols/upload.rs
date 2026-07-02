use std::path::PathBuf;

use anyhow::{anyhow, Result};
use tracing::info;

use crate::{
    api::{self, releases::ReleaseBuilder, symbol_sets::SymbolSetUpload},
    debug_symbols::{discover, report_problems},
    sourcemaps::args::{pack_version, ReleaseArgs, UploadConflictArgs},
    utils::git::get_git_info,
};

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The directory to scan for native debug symbol files (e.g. target/release).
    /// ELF executables, shared libraries, and `objcopy --only-keep-debug`
    /// companions with debug info are uploaded; everything else is skipped.
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

    info!("Found {} debug symbol file(s)", report.files.len());

    // Set up release info: explicit flags win, git info is metadata/fallback
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
    let release_id = created_release.map(|r| r.id.to_string());

    let mut uploads: Vec<SymbolSetUpload> = Vec::new();
    for file in report.files {
        info!(
            "Processing {} (debug id {})",
            file.path.display(),
            file.debug_id
        );
        uploads.push(file.into_upload(release_id.clone(), *include_source)?);
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
