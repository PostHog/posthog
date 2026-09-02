use std::{
    collections::{HashMap, HashSet},
    fs::OpenOptions,
    io::{Read, Seek, SeekFrom, Write},
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
        content::{MinifiedSourceFile, SourceMapFile},
        inject::get_release_for_maps,
        plain::inject::{is_javascript_file, is_stylesheet_file},
        source_pairs::{read_pairs, SourcePair},
    },
    utils::files::{content_hash, FileSelection, SourceFile},
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

    /// How the release is associated with exceptions. `event` (the default) leaves symbol sets
    /// unbound; the chunks already carry the release id in their injected snippet, so the release
    /// is resolved per event rather than per symbol set. `symbol-set` stamps the release id onto
    /// the uploaded symbol sets instead. Also settable via `POSTHOG_RELEASE_MODE`.
    #[arg(
        long,
        env = "POSTHOG_RELEASE_MODE",
        value_enum,
        default_value = "event"
    )]
    pub release_mode: ReleaseMode,
}

pub fn upload_cmd(args: &Args) -> Result<()> {
    args.file_selection.validate()?;
    context().capture_command_invoked("sourcemap_upload");
    upload(args, None)
}

pub fn upload(args: &Args, existing_release: Option<&Release>) -> Result<()> {
    // Resolve stdin once so the JavaScript upload and CSS cleanup scan the same paths.
    let file_selection = args.file_selection.clone().resolve_stdin()?;
    let selection = FileSelection::try_from(file_selection.clone())?;

    let pairs = read_pairs(
        selection.into_iter().filter(is_javascript_file),
        &args.public_path_prefix,
    );
    upload_pairs(args, pairs, existing_release, file_selection)
}

/// Upload `pairs`, then run the `--delete-after` cleanup scoped to `file_selection`
/// (already stdin-resolved). `process` calls this directly with the pairs inject just
/// wrote, so upload acts on the exact files inject stamped - in the state it left them
/// in - even when a bundler keeps writing into the scanned directory in the background
/// (e.g. Turbopack's filesystem-cache flush on Next.js 16.3+, posthog-js#4667).
pub fn upload_pairs(
    args: &Args,
    mut pairs: Vec<SourcePair>,
    existing_release: Option<&Release>,
    file_selection: FileSelectionArgs,
) -> Result<()> {
    if args.conflict.skip_on_conflict_ignored(args.release_mode) {
        warn!(
            "--skip-on-conflict is ignored with --release-mode=event. Every chunk's content changes with each release, so skipping conflicts would leave the previous release id in place. Overwriting instead."
        );
    }

    // Fingerprinting re-serializes and hashes every pair, which is not free for large
    // maps - skip it when nothing gets cleaned up.
    let cleanup_targets = if args.delete_after {
        pairs
            .iter()
            .map(cleanup_target)
            .collect::<Result<Vec<_>>>()?
    } else {
        Vec::new()
    };
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
        let stylesheet_targets = stylesheet_pairs
            .iter()
            .map(cleanup_target)
            .collect::<Result<Vec<_>>>()?;
        cleanup_pairs(
            cleanup_targets
                .into_iter()
                .chain(stylesheet_targets)
                .collect(),
        )
        .context("While cleaning up uploaded sourcemaps")?;
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

/// One processed pair's on-disk artifacts, fingerprinted at the moment the pair was
/// read for upload. Maps are hashed over their canonical JSON serialization, so the
/// comparison is stable across whitespace and key order.
struct CleanupTarget {
    source_path: PathBuf,
    sourcemap_path: PathBuf,
    source_hash: String,
    sourcemap_hash: String,
}

fn cleanup_target(pair: &SourcePair) -> Result<CleanupTarget> {
    let canonical_map = serde_json::to_string(&pair.sourcemap.inner.content)?;
    Ok(CleanupTarget {
        source_path: pair.source.inner.path.clone(),
        sourcemap_path: pair.sourcemap.inner.path.clone(),
        source_hash: content_hash([pair.source.inner.content.as_bytes()]),
        sourcemap_hash: content_hash([canonical_map.as_bytes()]),
    })
}

/// Strip the sourceMappingURL reference from each verified source, then delete the
/// maps that are safe to delete. A map can be shared by several chunks, so deletion
/// needs the outcome of every source first: a skipped source is (or was replaced by)
/// an artifact that may still reference the map. Skips warn instead of failing the
/// build - the upload already succeeded, and a bundler that keeps writing into the
/// directory (posthog-js#4667) may have removed or replaced files since they were read.
fn cleanup_pairs(targets: Vec<CleanupTarget>) -> Result<()> {
    // Maps are grouped by canonical path: distinct lexical paths or symlink aliases can
    // name the same file (deletion then operates on the first selected alias; further
    // aliases of an already-deleted map are left in place). A map shared by several chunks may only be deleted once every
    // source referencing it was verified - a skipped source is (or was replaced by) an
    // artifact that may still point at the map. Each sharing pair holds its own
    // in-memory copy of the map (default-mode injection stamps a different chunk id
    // into each copy, and the last save wins on disk), so the fingerprint of any of
    // them identifies the map as ours.
    let map_key = |path: &Path| path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
    let mut maps: HashMap<PathBuf, MapCleanup> = HashMap::new();
    for target in &targets {
        let verified = strip_verified_source(target)?;
        let entry = maps
            .entry(map_key(&target.sourcemap_path))
            .or_insert_with(|| MapCleanup {
                path: target.sourcemap_path.clone(),
                allowed_hashes: HashSet::new(),
                blocked: false,
            });
        entry.allowed_hashes.insert(target.sourcemap_hash.clone());
        entry.blocked |= !verified;
    }
    for map in maps.values() {
        if map.blocked {
            warn!(
                "Skipping sourcemap deletion for {}: a source referencing it was skipped",
                map.path.display()
            );
            continue;
        }
        delete_verified_map(&map.path, &map.allowed_hashes)?;
    }
    Ok(())
}

struct MapCleanup {
    path: PathBuf,
    allowed_hashes: HashSet<String>,
    blocked: bool,
}

/// Verify the source against its fingerprint and strip its sourceMappingURL reference.
/// Returns whether the source was verified. Verification reads through a read-only
/// handle, so a source that needs no stripping (e.g. one discovered through a sibling
/// map, with no sourceMappingURL comment) never requires write access. When a
/// reference does need stripping, the file is reopened writable and re-verified
/// through that handle before writing: a bundler replacing the file in between (write
/// new, then rename over the path) leaves the handle pointing at the old inode, so the
/// replacement is never overwritten with stale bytes.
fn strip_verified_source(target: &CleanupTarget) -> Result<bool> {
    let bytes = match std::fs::read(&target.source_path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            warn!(
                "Skipping cleanup for {}: the file no longer exists",
                target.source_path.display()
            );
            return Ok(false);
        }
        Err(e) => {
            return Err(e).context(format!(
                "Failed to read source file: {}",
                target.source_path.display()
            ))
        }
    };
    if content_hash([&bytes]) != target.source_hash {
        warn!(
            "Skipping cleanup for {}: the file changed since it was uploaded",
            target.source_path.display()
        );
        return Ok(false);
    }
    // The fingerprint matched the uploaded content, so the bytes are valid UTF-8.
    let content = String::from_utf8(bytes).with_context(|| {
        format!(
            "Source file is not valid UTF-8: {}",
            target.source_path.display()
        )
    })?;
    let mut source = MinifiedSourceFile {
        inner: SourceFile::new(target.source_path.clone(), content),
    };
    if !source.remove_sourcemap_reference() {
        return Ok(true);
    }

    let mut file = match OpenOptions::new()
        .read(true)
        .write(true)
        .open(&target.source_path)
    {
        Ok(file) => file,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            warn!(
                "Skipping cleanup for {}: the file no longer exists",
                target.source_path.display()
            );
            return Ok(false);
        }
        Err(e) => {
            return Err(e).context(format!(
                "Failed to open source file for writing: {}",
                target.source_path.display()
            ))
        }
    };
    let mut current = Vec::new();
    file.read_to_end(&mut current).with_context(|| {
        format!(
            "Failed to read source file: {}",
            target.source_path.display()
        )
    })?;
    if content_hash([&current]) != target.source_hash {
        warn!(
            "Skipping cleanup for {}: the file changed since it was uploaded",
            target.source_path.display()
        );
        return Ok(false);
    }
    let mut write = || -> std::io::Result<()> {
        file.set_len(0)?;
        file.seek(SeekFrom::Start(0))?;
        file.write_all(source.inner.content.as_bytes())
    };
    write().with_context(|| {
        format!(
            "Failed to save source file: {}",
            target.source_path.display()
        )
    })?;
    Ok(true)
}

/// Delete the map only if it is still one of the copies that was uploaded. The file is
/// renamed aside first: rename is atomic, so the verification and the final removal
/// operate on the exact same object, and a replacement the bundler drops at the
/// original path afterwards is never touched. A staged file that fails verification is
/// renamed back.
fn delete_verified_map(path: &Path, allowed_hashes: &HashSet<String>) -> Result<()> {
    let Some(file_name) = path.file_name().and_then(|name| name.to_str()) else {
        return Ok(());
    };
    let staged = path.with_file_name(format!(
        "{}.{}.posthog-delete",
        file_name,
        std::process::id()
    ));
    match std::fs::rename(path, &staged) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(e).context(format!("Failed to delete sourcemap: {}", path.display())),
    }
    let matches = SourceMapFile::load(&staged)
        .ok()
        .and_then(|map| serde_json::to_string(&map.inner.content).ok())
        .is_some_and(|canonical| allowed_hashes.contains(&content_hash([canonical.as_bytes()])));
    if matches {
        std::fs::remove_file(&staged)
            .with_context(|| format!("Failed to delete sourcemap: {}", path.display()))?;
    } else {
        warn!(
            "Skipping sourcemap deletion for {}: the map changed since it was uploaded",
            path.display()
        );
        restore_staged(&staged, path)?;
    }
    Ok(())
}

/// Put a staged file back at its original path without clobbering anything that
/// appeared there in the meantime: `hard_link` fails atomically when the destination
/// exists, in which case the displaced copy is dropped - its consumers already
/// reference the newer file at the original path.
fn restore_staged(staged: &Path, path: &Path) -> Result<()> {
    match std::fs::hard_link(staged, path) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
            warn!(
                "A newer sourcemap appeared at {}; discarding the displaced copy",
                path.display()
            );
        }
        // Filesystems without hard links: fall back to a plain rename.
        Err(_) => {
            return std::fs::rename(staged, path).with_context(|| {
                format!(
                    "Failed to restore sourcemap after skipped deletion: {}",
                    path.display()
                )
            });
        }
    }
    std::fs::remove_file(staged).with_context(|| {
        format!(
            "Failed to remove staged sourcemap copy: {}",
            staged.display()
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{sourcemaps::inject::inject_pairs, utils::files::FileSelection};

    const MAP_JSON: &str = r#"{"version":3,"sources":["a.ts"],"names":[],"mappings":""}"#;

    fn read_dir_pairs(dir: &Path) -> Vec<SourcePair> {
        let selection = FileSelection::from_roots(vec![dir.to_path_buf()]);
        read_pairs(selection.into_iter().filter(is_javascript_file), &None)
    }

    fn write_pair(dir: &Path, name: &str) -> (PathBuf, PathBuf) {
        let source_path = dir.join(format!("{name}.js"));
        let map_path = dir.join(format!("{name}.js.map"));
        std::fs::write(
            &source_path,
            format!("console.log(1);\n//# sourceMappingURL={name}.js.map\n"),
        )
        .unwrap();
        std::fs::write(&map_path, MAP_JSON).unwrap();
        (source_path, map_path)
    }

    #[test]
    fn cleanup_strips_references_and_deletes_maps() {
        let dir = tempfile::tempdir().unwrap();
        let (source_path, map_path) = write_pair(dir.path(), "chunk");
        let pairs = read_dir_pairs(dir.path());
        let target = cleanup_target(&pairs[0]).unwrap();

        cleanup_pairs(vec![target]).unwrap();

        let stripped = std::fs::read_to_string(&source_path).unwrap();
        assert!(!stripped.contains("sourceMappingURL"), "{stripped}");
        assert!(!map_path.exists());
    }

    #[test]
    fn cleanup_skips_missing_and_replaced_sources() {
        let dir = tempfile::tempdir().unwrap();

        // The source vanished after upload: cleanup must not fail the build, and must
        // leave the map alone.
        let (missing_source, orphan_map) = write_pair(dir.path(), "gone");
        // The source was replaced after upload: the replacement and its map are someone
        // else's artifacts and must stay untouched.
        let (replaced_source, replaced_map) = write_pair(dir.path(), "replaced");

        let targets = read_dir_pairs(dir.path())
            .iter()
            .map(|pair| cleanup_target(pair).unwrap())
            .collect::<Vec<_>>();

        std::fs::remove_file(&missing_source).unwrap();
        let replacement = "console.log(2);\n//# sourceMappingURL=replaced.js.map\n";
        std::fs::write(&replaced_source, replacement).unwrap();

        cleanup_pairs(targets).unwrap();

        assert!(orphan_map.exists());
        assert_eq!(
            std::fs::read_to_string(&replaced_source).unwrap(),
            replacement
        );
        assert!(replaced_map.exists());
    }

    #[test]
    fn cleanup_keeps_a_replaced_map_but_strips_the_unchanged_source() {
        let dir = tempfile::tempdir().unwrap();
        let (source_path, map_path) = write_pair(dir.path(), "chunk");
        let pairs = read_dir_pairs(dir.path());
        let target = cleanup_target(&pairs[0]).unwrap();

        let replacement_map = r#"{"version":3,"sources":["b.ts"],"names":[],"mappings":""}"#;
        std::fs::write(&map_path, replacement_map).unwrap();

        cleanup_pairs(vec![target]).unwrap();

        // Our source is unchanged, so its reference is stripped; the map was replaced
        // after upload, so the replacement stays in place.
        let stripped = std::fs::read_to_string(&source_path).unwrap();
        assert!(!stripped.contains("sourceMappingURL"), "{stripped}");
        assert_eq!(std::fs::read_to_string(&map_path).unwrap(), replacement_map);
    }

    #[test]
    fn overlapping_roots_yield_each_pair_once() {
        let dir = tempfile::tempdir().unwrap();
        write_pair(dir.path(), "chunk");

        let selection =
            FileSelection::from_roots(vec![dir.path().to_path_buf(), dir.path().to_path_buf()]);
        let pairs = read_pairs(selection.into_iter().filter(is_javascript_file), &None);

        assert_eq!(pairs.len(), 1);
    }

    #[test]
    fn cleanup_deletes_a_shared_map_matching_any_uploaded_copy() {
        let dir = tempfile::tempdir().unwrap();
        let shared_map = dir.path().join("shared.js.map");
        std::fs::write(&shared_map, MAP_JSON).unwrap();
        std::fs::write(
            dir.path().join("a.js"),
            "console.log(1);\n//# sourceMappingURL=shared.js.map\n",
        )
        .unwrap();
        std::fs::write(
            dir.path().join("b.js"),
            "console.log(2);\n//# sourceMappingURL=shared.js.map\n",
        )
        .unwrap();

        let mut targets = read_dir_pairs(dir.path())
            .iter()
            .map(|pair| cleanup_target(pair).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(targets.len(), 2);
        // Sharing pairs hold separately injected copies of the map, so their
        // fingerprints differ and only one matches the disk. Deletion must accept any
        // of them.
        targets[0].sourcemap_hash = "fingerprint-of-an-overwritten-copy".to_string();

        cleanup_pairs(targets).unwrap();

        assert!(!shared_map.exists());
    }

    #[test]
    fn cleanup_keeps_a_shared_map_while_any_source_was_skipped() {
        let dir = tempfile::tempdir().unwrap();
        let shared_map = dir.path().join("shared.js.map");
        std::fs::write(&shared_map, MAP_JSON).unwrap();
        let kept = dir.path().join("a.js");
        let replaced = dir.path().join("b.js");
        std::fs::write(
            &kept,
            "console.log(1);\n//# sourceMappingURL=shared.js.map\n",
        )
        .unwrap();
        std::fs::write(
            &replaced,
            "console.log(2);\n//# sourceMappingURL=shared.js.map\n",
        )
        .unwrap();

        let targets = read_dir_pairs(dir.path())
            .iter()
            .map(|pair| cleanup_target(pair).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(targets.len(), 2);

        let replacement = "console.log(3);\n//# sourceMappingURL=shared.js.map\n";
        std::fs::write(&replaced, replacement).unwrap();

        cleanup_pairs(targets).unwrap();

        // The unchanged source is stripped, but the map survives: the replacement
        // still references it.
        let stripped = std::fs::read_to_string(&kept).unwrap();
        assert!(!stripped.contains("sourceMappingURL"), "{stripped}");
        assert_eq!(std::fs::read_to_string(&replaced).unwrap(), replacement);
        assert!(shared_map.exists());
    }

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
