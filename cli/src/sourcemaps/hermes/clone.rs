use std::path::PathBuf;

use anyhow::{anyhow, bail, Result};
use tracing::{info, warn};

use crate::{
    invocation_context::context,
    sourcemaps::{
        content::SourceMapFile,
        hermes::{get_composed_map, inject::is_metro_bundle},
        source_pairs::read_pairs,
    },
};

#[derive(clap::Args)]
pub struct CloneArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    pub ignore: Vec<String>,
}

pub fn clone(args: &CloneArgs) -> Result<()> {
    context().capture_command_invoked("hermes_clone");

    let CloneArgs { directory, ignore } = args;

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;

    info!("Processing directory: {}", directory.display());
    let pairs = read_pairs(&directory, ignore, is_metro_bundle)?;

    if pairs.is_empty() {
        bail!("No source files found");
    }

    info!("Found {} pairs", pairs.len());

    let maps: Result<Vec<(&SourceMapFile, Option<SourceMapFile>)>> = pairs
        .iter()
        .map(|p| get_composed_map(p).map(|c| (&p.sourcemap, c)))
        .collect();

    let maps = maps?;

    for (minified, composed) in maps {
        let Some(mut composed) = composed else {
            warn!(
                "Could not find composed map for minified sourcemap {}",
                minified.inner.path.display()
            );
            continue;
        };

        // Copy metadata from source map to composed map
        if let Some(chunk_id) = minified.get_chunk_id() {
            composed.set_chunk_id(chunk_id);
        }

        if let Some(release_id) = minified.get_release_id() {
            composed.set_release_id(release_id);
        }

        composed.save()?;
        info!(
            "Successfully cloned metadata to {}",
            composed.inner.path.display()
        );
    }

    info!("Finished cloning metadata");
    Ok(())
}
