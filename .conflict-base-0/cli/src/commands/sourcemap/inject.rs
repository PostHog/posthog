use anyhow::{anyhow, bail, Ok, Result};
use std::path::Path;
use tracing::info;
use uuid;

use crate::utils::{posthog::capture_command_invoked, sourcemaps::read_pairs};

pub fn inject(directory: &Path, ignore_globs: &[String]) -> Result<()> {
    let capture_handle = capture_command_invoked("sourcemap_inject", None::<&str>);
    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;
    info!("Processing directory: {}", directory.display());
    let mut pairs = read_pairs(&directory, ignore_globs)?;
    if pairs.is_empty() {
        bail!("No source files found");
    }
    info!("Found {} pairs", pairs.len());
    let mut skipped_pairs = 0;
    for pair in &mut pairs {
        if pair.has_chunk_id() {
            skipped_pairs += 1;
            continue;
        }
        let chunk_id = uuid::Uuid::now_v7().to_string();
        pair.set_chunk_id(chunk_id)?;
    }
    if skipped_pairs > 0 {
        info!(
            "Skipped {} pairs because chunk IDs already exist",
            skipped_pairs
        );
    }

    // Write the source and sourcemaps back to disk
    for pair in &pairs {
        pair.save()?;
    }
    info!("Finished processing directory");
    let _ = capture_handle.join();
    Ok(())
}
