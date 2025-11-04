use std::path::PathBuf;

use anyhow::{anyhow, Ok, Result};
use tracing::{info, warn};

use crate::api::symbol_sets::{self, SymbolSetUpload};
use crate::invocation_context::context;

use crate::sourcemaps::hermes::get_composed_map;
use crate::sourcemaps::hermes::inject::is_metro_bundle;
use crate::sourcemaps::source_pairs::read_pairs;

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    pub ignore: Vec<String>,
}

pub fn upload(args: &Args) -> Result<()> {
    context().capture_command_invoked("hermes_upload");
    let Args { directory, ignore } = args;

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;

    info!("Processing directory: {}", directory.display());
    let pairs = read_pairs(&directory, ignore, is_metro_bundle, &None)?;

    let maps: Result<Vec<_>> = pairs.iter().map(get_composed_map).collect();
    let maps = maps?;

    let mut uploads: Vec<SymbolSetUpload> = Vec::new();
    for map in maps.into_iter() {
        let Some(map) = map else {
            continue;
        };

        if map.get_chunk_id().is_none() {
            warn!("Skipping map {}, no chunk ID", map.inner.path.display());
            continue;
        }

        uploads.push(map.try_into()?);
    }

    info!("Found {} bundles to upload", uploads.len());

    symbol_sets::upload(&uploads, 100)?;

    Ok(())
}
