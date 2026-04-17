use std::{path::PathBuf, time::Instant};

use anyhow::{anyhow, Result};
use serde_json::json;
use tracing::{info, warn};
use walkdir::WalkDir;

use crate::api::releases::is_hash_already_in_use;
use crate::api::symbol_sets::{self, SymbolSetUpload};
use crate::invocation_context::context;
use crate::sourcemaps::args::ReleaseArgs;
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
}

pub fn upload(args: &Args) -> Result<()> {
    context().capture_command_invoked("hermes_upload");
    let Args {
        directory,
        release,
        batch_size,
    } = args;

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;

    info!("Processing directory: {}", directory.display());
    let maps = read_maps(&directory);

    // Get or create a release if project/version are provided or if any map is missing a release_id.
    //
    // If a prior step has just created the release, the `by_hash` GET used inside
    // `get_release_for_maps` can briefly serve a stale 404 — the follow-up POST then fails with
    // `Hash id ... already in use`. We only swallow that error when every map already carries a
    // `release_id`; otherwise skipping would silently upload orphan symbol sets.
    let created_release_id = match get_release_for_maps(&directory, release.clone(), maps.iter()) {
        Ok(result) => result.map(|r| r.id.to_string()),
        Err(err) if is_hash_already_in_use(&err) && maps.iter().all(|m| m.has_release_id()) => {
            warn!(
                "release already exists (likely created by a prior step in this run); keeping release_ids on existing maps: {}",
                err
            );
            None
        }
        Err(err) => return Err(err),
    };

    let mut uploads: Vec<SymbolSetUpload> = Vec::new();
    for mut map in maps.into_iter() {
        if map.get_chunk_id().is_none() {
            warn!("Skipping map {}, no chunk ID", map.inner.path.display());
            continue;
        }

        // Override release_id if we created/fetched one
        if let Some(ref release_id) = created_release_id {
            map.set_release_id(Some(release_id.clone()));
        }

        uploads.push(map.try_into()?);
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
        ],
    );

    let started_at = Instant::now();
    let upload_result =
        symbol_sets::upload_with_retry(uploads, *batch_size, release.skip_release_on_fail, false);
    let duration_ms = started_at.elapsed().as_millis();

    let mut props = vec![
        ("type", json!("hermes")),
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
