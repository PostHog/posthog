use std::{path::PathBuf, time::Instant};

use anyhow::{anyhow, Result};
use serde_json::json;
use tracing::{info, warn};
use walkdir::WalkDir;

use crate::api::symbol_sets::{self, SymbolSetUpload};
use crate::invocation_context::context;
use crate::sourcemaps::args::{ReleaseArgs, ReleaseMode, UploadConflictArgs};
use crate::sourcemaps::content::SourceMapFile;
use crate::sourcemaps::inject::get_release_for_maps;

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,

    #[clap(flatten)]
    pub release: ReleaseArgs,

    #[clap(flatten)]
    pub conflict: UploadConflictArgs,

    /// How the release is associated with exceptions. `symbol-set` is the default. It stamps the
    /// release id onto the uploaded maps. An exception then takes the release of the maps its
    /// frames resolved against. EXPERIMENTAL `event` leaves the maps release-independent. Each
    /// event then resolves its own release from the app version and namespace the SDK already
    /// sends, so the release coordinates must match the app's. Both modes create the release.
    /// Also settable via `POSTHOG_RELEASE_MODE`.
    #[arg(
        long,
        env = "POSTHOG_RELEASE_MODE",
        value_enum,
        default_value = "symbol-set"
    )]
    pub release_mode: ReleaseMode,
}

pub fn upload(args: &Args) -> Result<()> {
    context().capture_command_invoked("hermes_upload");
    let Args {
        directory,
        release,
        batch_size,
        conflict,
        release_mode,
    } = args;

    if conflict.skip_on_conflict_ignored(*release_mode) {
        warn!(
            "--skip-on-conflict is ignored with --release-mode=event. Skipping a conflict would \
             keep the previously uploaded map, so the build that changes release mode would \
             fail to replace it. Overwriting instead."
        );
    }

    // Event mode leaves nothing on the symbol set for the server to use. An exception then
    // resolves its release only from the app metadata on the event. Coordinates that come from
    // git instead of explicit flags do not match that metadata. The exception then reports no
    // release, and nothing in the output says so. The build number counts as a coordinate: the
    // server packs it into the version it keys on, so a release without one matches no event that
    // carries `$app_build`.
    if *release_mode == ReleaseMode::Event
        && (release.name.is_none() || release.version.is_none() || release.build.is_none())
    {
        warn!(
            "--release-mode=event resolves each exception's release from the app's namespace and \
             version. Pass --release-name, --release-version and --build matching the app's bundle \
             identifier or applicationId, its version and its build number, or exceptions will \
             report no release."
        );
    }

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;

    info!("Processing directory: {}", directory.display());
    let maps = read_maps(&directory);

    // Get or create a release if project/version are provided or if any map is missing a release_id
    let created_release_id =
        get_release_for_maps(&directory, release.clone(), maps.iter())?.map(|r| r.id.to_string());

    let mut uploads: Vec<SymbolSetUpload> = Vec::new();
    let mut empty_skipped = 0usize;
    for mut map in maps.into_iter() {
        if map.get_upload_chunk_id().is_none() {
            warn!("Skipping map {}, no chunk ID", map.inner.path.display());
            continue;
        }
        if map.is_empty() {
            warn!(
                "Skipping {}: sourcemap is empty (no mappings/sources/names) — likely a bundler misconfiguration",
                map.inner.path.display()
            );
            empty_skipped += 1;
            continue;
        }

        // Both modes create the release, so the server has a row to resolve an event's
        // `$app_namespace` / `$app_version` / `$app_build` onto. Event mode only skips the
        // binding. A chunk id comes from the bundle's own content, so one symbol set serves
        // every release. Without this, a later release reports the release that uploaded first.
        match release_mode {
            ReleaseMode::Event => map.set_release_id(None),
            ReleaseMode::SymbolSet => {
                // Override release_id if we created/fetched one
                if let Some(ref release_id) = created_release_id {
                    map.set_release_id(Some(release_id.clone()));
                }
            }
        }

        uploads.push(map.try_into()?);
    }

    // A run that discovers nothing must fail rather than exit green: in build pipelines this
    // command runs right after bundling, so an empty result means the maps or their ids went
    // missing, and a silent success ships a build whose exceptions never symbolicate.
    if uploads.is_empty() {
        anyhow::bail!(
            "No hermes sourcemaps with a chunk id found under {} — nothing was uploaded. \
             Check that bundling produced .map files and that they carry a chunk id or debugId.",
            directory.display()
        );
    }

    info!("Found {} maps to upload", uploads.len());

    let file_count = uploads.len();
    let total_bytes: usize = uploads.iter().map(|u| u.data.len()).sum();
    context().capture_event(
        "error_tracking_cli_sourcemaps_upload_started",
        vec![
            ("type", json!("hermes")),
            ("file_count", json!(file_count)),
            ("total_bytes", json!(total_bytes)),
            ("empty_skipped", json!(empty_skipped)),
        ],
    );

    // A hermes chunk id comes from the bundle content, and the release id sits inside the
    // uploaded map. The build that changes release mode therefore sends the same id with
    // different bytes, and the server refuses it. Event mode overwrites so that build passes.
    let conflict = conflict.resolve(*release_mode);

    let started_at = Instant::now();
    let (summary, upload_result) = symbol_sets::upload_with_retry(
        uploads,
        *batch_size,
        release.skip_release_on_fail,
        conflict.force,
        conflict.skip_on_conflict,
    );
    let duration_ms = started_at.elapsed().as_millis();

    let mut props = vec![
        ("type", json!("hermes")),
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
    Ok(())
}

fn read_maps(directory: &PathBuf) -> Vec<SourceMapFile> {
    WalkDir::new(directory)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|e| e.file_type().is_file())
        .map(|e| {
            let path = e.path().canonicalize()?;
            SourceMapFile::load(&path)
        })
        .filter_map(Result::ok)
        .collect()
}
