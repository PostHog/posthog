use std::path::PathBuf;

use anyhow::{anyhow, Ok, Result};
use tracing::{info, warn};
use walkdir::WalkDir;

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

    #[clap(flatten)]
    pub release: ReleaseArgs,
}

pub fn upload(args: &Args) -> Result<()> {
    context().capture_command_invoked("hermes_upload");
    let Args { directory, release } = args;

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
