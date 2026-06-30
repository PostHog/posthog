use std::{path::PathBuf, time::Instant};

use anyhow::{Context, Result};
use serde_json::json;
use tracing::{debug, info, warn};

/// Sibling-JS size below which an empty sourcemap is treated as a harmless
/// bundler-generated wrapper (e.g. Turbopack App Router page entries,
/// webpack re-export shims). Observed wrapper files in the wild are
/// under 1 KiB; 2 KiB leaves comfortable headroom for tools that inject
/// extra glue (PostHog chunk-id IIFE, etc.) without misclassifying real code.
const WRAPPER_JS_SIZE_THRESHOLD_BYTES: usize = 2048;

use crate::{
    api::{
        releases::Release,
        symbol_sets::{self, SymbolSetUpload},
    },
    invocation_context::context,
    sourcemaps::{
        args::{FileSelectionArgs, ReleaseArgs, UploadConflictArgs},
        content::MinifiedSourceFile,
        inject::get_release_for_maps,
        plain::inject::is_javascript_file,
        source_pairs::read_pairs,
    },
    utils::files::{delete_files, FileSelection},
};

#[derive(clap::Args, Clone)]
pub struct Args {
    #[clap(flatten)]
    pub file_selection: FileSelectionArgs,

    /// If your bundler adds a public path prefix to sourcemap URLs,
    /// we need to ignore it while searching for them
    /// For use alongside e.g. esbuilds "publicPath" config setting.
    #[arg(short, long)]
    pub public_path_prefix: Option<String>,

    /// Whether to delete the source map files and strip sourceMappingURL comments after uploading them
    /// [default: false]
    #[arg(long, default_value = "false")]
    pub delete_after: bool,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,

    #[clap(flatten)]
    pub release: ReleaseArgs,

    #[clap(flatten)]
    pub conflict: UploadConflictArgs,

    /// DEPRECATED - this flag is a no-op. Use top-level `--skip-ssl-verification` instead.
    #[arg(long)]
    pub skip_ssl_verification: bool,
}

pub fn upload_cmd(args: &Args) -> Result<()> {
    args.file_selection.validate()?;
    context().capture_command_invoked("sourcemap_upload");
    upload(args, None)
}

pub fn upload(args: &Args, existing_release: Option<&Release>) -> Result<()> {
    let selection = FileSelection::try_from(args.file_selection.clone())?;

    let mut pairs = read_pairs(
        selection.into_iter().filter(is_javascript_file),
        &args.public_path_prefix,
    );

    let sourcemap_paths = pairs
        .iter()
        .map(|pair| pair.sourcemap.inner.path.clone())
        .collect::<Vec<_>>();
    let source_paths = pairs
        .iter()
        .map(|pair| pair.source.inner.path.clone())
        .collect::<Vec<_>>();
    info!("Found {} chunks to upload", pairs.len());

    // Reuse the pre-resolved release if available, otherwise fetch or create one
    let created_release_id = if let Some(r) = existing_release {
        Some(r.id.to_string())
    } else {
        let cwd = std::env::current_dir()?;
        get_release_for_maps(
            &cwd,
            args.release.clone(),
            pairs.iter().map(|p| &p.sourcemap),
        )?
        .map(|r| r.id.to_string())
    };

    // Override release_id if we created/fetched one
    if let Some(ref release_id) = created_release_id {
        for pair in &mut pairs {
            pair.set_release_id(Some(release_id.clone()));
        }
    }

    let (empty_pairs, valid_pairs): (Vec<_>, Vec<_>) = pairs
        .into_iter()
        .partition(|pair| pair.sourcemap.is_empty());
    let mut empty_skipped_wrapper = 0usize;
    let mut empty_skipped_suspect = 0usize;
    for pair in &empty_pairs {
        let js_size = pair.source.inner.content.len();
        let map_path = pair.sourcemap.inner.path.display();
        if js_size < WRAPPER_JS_SIZE_THRESHOLD_BYTES {
            empty_skipped_wrapper += 1;
            debug!(
                "Skipping {}: sourcemap is empty and sibling JS is {} bytes — bundler-generated wrapper, nothing to symbolicate",
                map_path, js_size
            );
        } else {
            empty_skipped_suspect += 1;
            warn!(
                "Skipping {}: sourcemap is empty but sibling JS is {} bytes — likely a bundler misconfiguration. Check your bundler's source-map setting (e.g. webpack `devtool`, Next.js `productionBrowserSourceMaps`, server compiler config).",
                map_path, js_size
            );
        }
    }
    let empty_skipped = empty_pairs.len();

    let uploads = valid_pairs
        .into_iter()
        .map(TryInto::try_into)
        .collect::<Result<Vec<SymbolSetUpload>>>()
        .context("While preparing files for upload")?;

    let file_count = uploads.len();
    let total_bytes: usize = uploads.iter().map(|u| u.data.len()).sum();
    context().capture_event(
        "error_tracking_cli_sourcemaps_upload_started",
        vec![
            ("type", json!("plain")),
            ("file_count", json!(file_count)),
            ("total_bytes", json!(total_bytes)),
            ("empty_skipped", json!(empty_skipped)),
            ("empty_skipped_wrapper", json!(empty_skipped_wrapper)),
            ("empty_skipped_suspect", json!(empty_skipped_suspect)),
        ],
    );

    let started_at = Instant::now();
    let upload_result = symbol_sets::upload_with_retry(
        uploads,
        args.batch_size,
        args.release.skip_release_on_fail,
        args.conflict.force,
        args.conflict.skip_on_conflict,
    );
    let duration_ms = started_at.elapsed().as_millis();

    let mut props = vec![
        ("type", json!("plain")),
        ("file_count", json!(file_count)),
        ("total_bytes", json!(total_bytes)),
        ("duration_ms", json!(duration_ms)),
        ("success", json!(upload_result.is_ok())),
    ];
    if let Err(ref e) = upload_result {
        props.push(("error", json!(format!("{:#}", e))));
    }
    context().capture_event("error_tracking_cli_sourcemaps_upload_finished", props);

    upload_result?;

    if args.delete_after {
        remove_sourcemap_references(source_paths)
            .context("While stripping sourcemap references")?;
        delete_files(sourcemap_paths).context("While deleting sourcemaps")?;
    }

    Ok(())
}

fn remove_sourcemap_references(paths: Vec<PathBuf>) -> Result<()> {
    for path in paths {
        let mut source = MinifiedSourceFile::load(&path)
            .with_context(|| format!("Failed to read source file: {}", path.display()))?;
        if source.remove_sourcemap_reference() {
            source
                .save()
                .with_context(|| format!("Failed to save source file: {}", path.display()))?;
        }
    }
    Ok(())
}
