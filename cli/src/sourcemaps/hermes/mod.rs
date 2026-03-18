use std::path::PathBuf;

use anyhow::{anyhow, Context, Result};
use clap::Subcommand;
use tracing::info;

use crate::sourcemaps::{content::SourceMapFile, inject::InjectArgs, source_pairs::SourcePair};

pub mod clone;
pub mod inject;
pub mod upload;

#[derive(Subcommand)]
pub enum HermesSubcommand {
    /// Inject your bundled chunk with a posthog chunk ID
    Inject(InjectArgs),
    /// Upload the bundled chunk to PostHog
    Upload(upload::Args),
    /// Clone chunk_id and release_id metadata from bundle maps to composed maps
    Clone(clone::CloneArgs),
}

pub fn get_composed_map(pair: &SourcePair) -> Result<Option<SourceMapFile>> {
    let sourcemap_path = &pair.sourcemap.inner.path;

    // Look for composed map: change .bundle.map to .bundle.hbc.composed.map
    let composed_path = sourcemap_path
        .to_str()
        .and_then(|s| {
            if s.ends_with(".bundle.map") {
                Some(PathBuf::from(
                    s.replace(".bundle.map", ".bundle.hbc.composed.map"),
                ))
            } else if s.ends_with(".jsbundle.map") {
                Some(PathBuf::from(
                    s.replace(".jsbundle.map", ".jsbundle.hbc.composed.map"),
                ))
            } else {
                None
            }
        })
        .ok_or_else(|| anyhow!("Could not determine composed map path for {sourcemap_path:?}"))?;

    if !composed_path.exists() {
        info!(
            "Skipping {} - no composed map found at {}",
            sourcemap_path.display(),
            composed_path.display()
        );
        return Ok(None);
    }

    Ok(Some(SourceMapFile::load(&composed_path).context(
        format!("reading composed map at {composed_path:?}"),
    )?))
}
