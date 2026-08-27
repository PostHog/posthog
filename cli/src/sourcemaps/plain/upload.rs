use std::{
    path::{Path, PathBuf},
    time::Instant,
};

use anyhow::{Context, Result};
use rayon::iter::{IntoParallelIterator, ParallelIterator};
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
        symbol_sets::{self, dedup_uploads_by_chunk_id, SymbolSetUpload},
    },
    invocation_context::context,
    sourcemaps::{
        args::{
            FileSelectionArgs, ReleaseArgs, ReleaseMode, UploadConcurrencyArgs, UploadConflictArgs,
        },
        content::MinifiedSourceFile,
        inject::get_release_for_maps,
        plain::inject::{is_javascript_file, is_stylesheet_file},
        source_pairs::{read_pairs, SourcePair},
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

    #[clap(flatten)]
    pub upload_concurrency: UploadConcurrencyArgs,

    /// DEPRECATED - this flag is a no-op. Use top-level `--skip-ssl-verification` instead.
    #[arg(long)]
    pub skip_ssl_verification: bool,

    /// How the release is associated with exceptions. `symbol-set` (the default) stamps the
    /// release id onto the uploaded symbol sets: the previous behavior. EXPERIMENTAL `event`
    /// leaves symbol sets unbound; the chunks already carry the release id in their injected
    /// snippet, so the release is resolved per event rather than per symbol set. Also settable
    /// via `POSTHOG_RELEASE_MODE`.
    #[arg(
        long,
        env = "POSTHOG_RELEASE_MODE",
        value_enum,
        default_value = "symbol-set"
    )]
    pub release_mode: ReleaseMode,
}

pub fn upload_cmd(args: &Args) -> Result<()> {
    args.file_selection.validate()?;
    context().capture_command_invoked("sourcemap_upload");
    upload(args, None)
}

pub fn upload(args: &Args, existing_release: Option<&Release>) -> Result<()> {
    if args.conflict.skip_on_conflict_ignored(args.release_mode) {
        warn!(
            "--skip-on-conflict is ignored with --release-mode=event. Every chunk's content changes with each release, so skipping conflicts would leave the previous release id in place. Overwriting instead."
        );
    }

    // Resolve stdin once so the JavaScript upload and CSS cleanup scan the same paths.
    let file_selection = args.file_selection.clone().resolve_stdin()?;
    let selection = FileSelection::try_from(file_selection.clone())?;

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

    // Reuse the pre-resolved release if available, otherwise fetch or create one. Skipped entirely
    // in event mode: inject already put the release id inside the chunks, and resolving one here
    // would only serve to stamp it onto the symbol sets, which is the binding event mode avoids.
    let created_release_id = if args.release_mode == ReleaseMode::Event {
        None
    } else if let Some(r) = existing_release {
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

    let uploads = prepare_uploads(valid_pairs, args.release_mode)?;

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

    let conflict = args.conflict.resolve(args.release_mode);

    let started_at = Instant::now();
    let (summary, upload_result) = symbol_sets::upload_with_retry_and_concurrency(
        uploads,
        args.batch_size,
        args.release.skip_release_on_fail,
        conflict.force,
        conflict.skip_on_conflict,
        args.upload_concurrency.concurrency,
    );
    let duration_ms = started_at.elapsed().as_millis();

    let mut props = vec![
        ("type", json!("plain")),
        ("file_count", json!(file_count)),
        ("total_bytes", json!(total_bytes)),
        ("duration_ms", json!(duration_ms)),
        ("success", json!(upload_result.is_ok())),
    ];
    props.extend(summary.telemetry_props());
    if let Err(ref e) = upload_result {
        props.push(("error", json!(format!("{:#}", e))));
    }
    context().capture_event("error_tracking_cli_sourcemaps_upload_finished", props);

    upload_result?;

    if args.delete_after {
        let cleanup_roots = canonical_selection_roots(&file_selection.directory);
        let stylesheet_selection = FileSelection::try_from(file_selection)?;
        let stylesheet_pairs = read_pairs(
            stylesheet_selection.into_iter().filter(is_stylesheet_file),
            &args.public_path_prefix,
        );
        let (stylesheet_pairs, unsafe_stylesheet_pairs): (Vec<_>, Vec<_>) = stylesheet_pairs
            .into_iter()
            .partition(|pair| path_is_within_roots(&pair.sourcemap.inner.path, &cleanup_roots));
        for pair in unsafe_stylesheet_pairs {
            warn!(
                "Skipping CSS sourcemap cleanup for {} because it resolves outside the selected paths",
                pair.sourcemap.inner.path.display()
            );
        }
        let stylesheet_source_paths = stylesheet_pairs
            .iter()
            .map(|pair| pair.source.inner.path.clone())
            .collect::<Vec<_>>();
        let stylesheet_sourcemap_paths = stylesheet_pairs
            .iter()
            .map(|pair| pair.sourcemap.inner.path.clone())
            .collect::<Vec<_>>();

        remove_sourcemap_references(
            source_paths
                .into_iter()
                .chain(stylesheet_source_paths)
                .collect(),
        )
        .context("While stripping sourcemap references")?;
        delete_files(
            sourcemap_paths
                .into_iter()
                .chain(stylesheet_sourcemap_paths)
                .collect(),
        )
        .context("While deleting sourcemaps")?;
    }

    Ok(())
}

/// Build the upload payloads for `pairs`, at most one per chunk id. Event mode derives the id
/// from content, so a hashless alias copied beside `app-<hash>.js` collides with its original.
fn prepare_uploads(
    pairs: Vec<SourcePair>,
    release_mode: ReleaseMode,
) -> Result<Vec<SymbolSetUpload>> {
    // Payload preparation (serialization + zstd compression) is CPU-bound,
    // so spread it across cores.
    let uploads = pairs
        .into_par_iter()
        .map(|pair| pair.into_upload(release_mode))
        .collect::<Result<Vec<SymbolSetUpload>>>()
        .context("While preparing files for upload")?;

    Ok(dedup_uploads_by_chunk_id(uploads))
}

fn canonical_selection_roots(paths: &[PathBuf]) -> Vec<PathBuf> {
    paths
        .iter()
        .filter_map(|path| path.canonicalize().ok())
        .filter_map(|path| {
            if path.is_dir() {
                Some(path)
            } else {
                path.parent().map(Path::to_path_buf)
            }
        })
        .collect()
}

fn path_is_within_roots(path: &Path, roots: &[PathBuf]) -> bool {
    path.canonicalize()
        .is_ok_and(|path| roots.iter().any(|root| path.starts_with(root)))
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{sourcemaps::inject::inject_pairs, utils::files::FileSelection};

    #[test]
    fn stylesheet_cleanup_only_accepts_maps_inside_selected_roots() {
        let dir = tempfile::tempdir().expect("Failed to create temp dir");
        let output = dir.path().join("output");
        std::fs::create_dir(&output).expect("Failed to create output directory");
        let selected_source = output.join("app.css");
        let selected_map = output.join("app.css.map");
        let outside_map = dir.path().join("outside.css.map");
        std::fs::write(&selected_source, "").expect("Failed to write selected source");
        std::fs::write(&selected_map, "{}").expect("Failed to write selected map");
        std::fs::write(&outside_map, "{}").expect("Failed to write outside map");

        let directory_roots = canonical_selection_roots(std::slice::from_ref(&output));
        let file_roots = canonical_selection_roots(std::slice::from_ref(&selected_source));

        assert!(path_is_within_roots(&selected_map, &directory_roots));
        assert!(path_is_within_roots(&selected_map, &file_roots));
        assert!(!path_is_within_roots(&outside_map, &directory_roots));
        assert!(!path_is_within_roots(
            &output.join("..").join("outside.css.map"),
            &directory_roots
        ));
    }

    #[cfg(unix)]
    #[test]
    fn stylesheet_cleanup_rejects_symlinks_outside_selected_roots() {
        let dir = tempfile::tempdir().expect("Failed to create temp dir");
        let output = dir.path().join("output");
        std::fs::create_dir(&output).expect("Failed to create output directory");
        let outside_map = dir.path().join("outside.css.map");
        let symlinked_map = output.join("app.css.map");
        std::fs::write(&outside_map, "{}").expect("Failed to write outside map");
        std::os::unix::fs::symlink(&outside_map, &symlinked_map)
            .expect("Failed to create sourcemap symlink");

        let roots = canonical_selection_roots(std::slice::from_ref(&output));

        assert!(!path_is_within_roots(&symlinked_map, &roots));
    }

    #[test]
    fn event_mode_uploads_one_payload_per_chunk_id() {
        // The hashless copy keeps the original's sourceMappingURL, so both files are identical.
        let dir = tempfile::tempdir().expect("Failed to create temp dir");
        let entry = "console.log(\"hi\");\n//# sourceMappingURL=app-BKG53LDN.js.map\n";
        std::fs::write(dir.path().join("app-BKG53LDN.js"), entry).expect("Failed to write entry");
        std::fs::write(dir.path().join("app.js"), entry).expect("Failed to write hashless copy");
        std::fs::write(
            dir.path().join("app-BKG53LDN.js.map"),
            r#"{"version":3,"sources":["app.ts"],"sourcesContent":["console.log('hi')\n"],"mappings":"AAAA,QAAQ,IAAI,IAAI","names":[]}"#,
        )
        .expect("Failed to write sourcemap");

        let selection = FileSelection::from_roots(vec![dir.path().to_path_buf()])
            .include(vec![])
            .expect("Failed to build selection")
            .exclude(vec![])
            .expect("Failed to build selection");
        let pairs = read_pairs(selection.into_iter().filter(is_javascript_file), &None);
        assert_eq!(pairs.len(), 2);

        let injected = inject_pairs(pairs, None).expect("Failed to inject pairs");
        let chunk_ids: Vec<_> = injected.iter().map(|pair| pair.get_chunk_id()).collect();
        assert_eq!(chunk_ids[0], chunk_ids[1]);

        let uploads =
            prepare_uploads(injected, ReleaseMode::Event).expect("Failed to prepare uploads");
        assert_eq!(uploads.len(), 1);
    }
}
