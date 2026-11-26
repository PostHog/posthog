use std::{fs, path::PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use posthog_symbol_data::write_symbol_data;
use tracing::info;

use crate::{
    api::{
        self,
        releases::ReleaseBuilder,
        symbol_sets::{SymbolSetUpload, MAX_FILE_SIZE},
    },
    jvm::sources::{bundle_sources, collect_sources, MAP_ID_PROPERTY, META_PROPERTIES_FILE},
    sourcemaps::args::{pack_version, ReleaseArgs, UploadConflictArgs},
    utils::git::get_git_info,
};

#[derive(clap::Args, Clone)]
pub struct Args {
    /// A directory of Java or Kotlin source files, such as `src/main/java`. Repeat it for each
    /// source directory of the build. Test sources and build output inside it are skipped.
    #[arg(short, long = "source", required = true)]
    pub sources: Vec<PathBuf>,

    /// After the upload, write `posthog-meta.properties` with the id of the uploaded sources into
    /// this directory. Package it on the application's classpath, so the PostHog SDK sends the id
    /// with each exception and PostHog can find the sources.
    #[arg(long, value_name = "DIR")]
    pub meta_out: Option<PathBuf>,

    /// When no PostHog credentials are configured, skip the upload with a warning instead of
    /// failing. Build plugins pass it, so that builds on machines without PostHog credentials
    /// keep working. A skipped upload writes no `posthog-meta.properties`.
    #[arg(long)]
    pub skip_without_credentials: bool,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,

    #[clap(flatten)]
    pub release: ReleaseArgs,

    #[clap(flatten)]
    pub conflict: UploadConflictArgs,
}

pub fn upload(args: &Args) -> Result<()> {
    let Args {
        sources: roots,
        meta_out,
        // Handled before the credentials are loaded, in `commands.rs`.
        skip_without_credentials: _,
        batch_size,
        release,
        conflict,
    } = args;

    let sources = collect_sources(roots)?;
    if sources.is_empty() {
        let roots: Vec<String> = roots.iter().map(|r| r.display().to_string()).collect();
        bail!(
            "No Java or Kotlin source files found in {}",
            roots.join(", ")
        );
    }
    let file_count = sources.len();

    let resolved_release = release.resolve_info_plist()?;
    let ReleaseArgs {
        name,
        version,
        build,
        info_plist: _,
        skip_release_on_fail,
    } = &resolved_release;

    let directory = roots[0]
        .canonicalize()
        .map_err(|e| anyhow!("Path {} canonicalization failed: {}", roots[0].display(), e))?;
    let mut release_builder = get_git_info(Some(directory))?
        .map(ReleaseBuilder::init_from_git)
        .unwrap_or_default();
    if let Some(name) = name {
        release_builder.with_name(name);
    }
    if let Some(ref v) = pack_version(version, build) {
        release_builder.with_version(v);
    }
    // Bind the sources to the release this build resolved, so that frames resolved with them
    // carry its git metadata and their events resolve to this release.
    let release = release_builder
        .can_create()
        .then(|| release_builder.fetch_or_create())
        .transpose()?;

    let bundle = bundle_sources(sources, release.as_ref().map(|r| r.hash_id.as_str()))?;
    info!("Bundled {file_count} source files as {}", bundle.id);

    let data = write_symbol_data(bundle.bundle)?;
    // The upload skips a larger symbol set with only a warning. Its id must not reach the app then,
    // because PostHog has no sources for it, and every frame that carries it fails to resolve.
    if data.len() > MAX_FILE_SIZE {
        bail!(
            "The {file_count} source files bundle to {} MB, more than the {} MB PostHog accepts. \
             Upload fewer source directories, for example without generated sources.",
            data.len().div_ceil(1024 * 1024),
            MAX_FILE_SIZE / (1024 * 1024),
        );
    }

    let to_upload = SymbolSetUpload {
        chunk_id: bundle.id.clone(),
        release_id: release.map(|r| r.id.to_string()),
        data,
        content_hash: Some(bundle.content_hash),
    };
    let (_summary, upload_result) = api::symbol_sets::upload_with_retry(
        vec![to_upload],
        *batch_size,
        *skip_release_on_fail,
        conflict.force,
        conflict.skip_on_conflict,
    );
    upload_result?;

    // Written only after a successful upload: an app that sends an id PostHog has no sources for
    // gets its frames marked as failed to resolve instead of shown as they are.
    if let Some(dir) = meta_out {
        fs::create_dir_all(dir).with_context(|| format!("Failed to create {}", dir.display()))?;
        let path = dir.join(META_PROPERTIES_FILE);
        fs::write(&path, format!("{MAP_ID_PROPERTY}={}\n", bundle.id))
            .with_context(|| format!("Failed to write {}", path.display()))?;
        info!("Wrote {}", path.display());
    }

    crate::safe_println!("{}", bundle.id);
    Ok(())
}
