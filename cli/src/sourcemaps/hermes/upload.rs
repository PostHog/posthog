use std::path::PathBuf;

use anyhow::{anyhow, Ok, Result};
use tracing::{info, warn};
use walkdir::WalkDir;

use crate::api::symbol_sets::{self, SymbolSetUpload};
use crate::invocation_context::context;

use crate::sourcemaps::content::SourceMapFile;

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,
}

pub fn upload(args: &Args) -> Result<()> {
    context().capture_command_invoked("hermes_upload");
    let Args { directory } = args;

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;

    info!("Processing directory: {}", directory.display());
    let maps = read_maps(&directory);

    let mut uploads: Vec<SymbolSetUpload> = Vec::new();
    for map in maps.into_iter() {
        if map.get_chunk_id().is_none() {
            warn!("Skipping map {}, no chunk ID", map.inner.path.display());
            continue;
        }

        uploads.push(map.try_into()?);
    }

    info!("Found {} maps to upload", uploads.len());

    symbol_sets::upload(&uploads, 100)?;

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
