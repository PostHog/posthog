use std::path::PathBuf;

use anyhow::{anyhow, bail, Result};
use tracing::{info, warn};

use crate::{
    invocation_context::context,
    sourcemaps::{
        content::SourceMapFile,
        hermes::{get_composed_map, inject::is_metro_bundle},
        inject::{get_release_for_maps, get_release_for_pairs},
        source_pairs::read_pairs,
    },
};

#[derive(clap::Args)]
pub struct CloneArgs {
    /// The path of the minified source map
    #[arg(short, long)]
    pub minified_map_path: PathBuf,

    /// The path of the composed source map
    #[arg(short, long)]
    pub composed_map_path: PathBuf,

    /// The project name associated with the uploaded chunks. Required to have the uploaded chunks associated with
    /// a specific release. We will try to auto-derive this from git information if not provided. Strongly recommended
    /// to be set explicitly during release CD workflows. Only necessary if no project was provided during injection.
    #[arg(long)]
    pub project: Option<String>,

    /// The version of the project - this can be a version number, semantic version, or a git commit hash. Required
    /// to have the uploaded chunks associated with a specific release.
    #[arg(long)]
    pub version: Option<String>,
}

pub fn clone(args: &CloneArgs) -> Result<()> {
    context().capture_command_invoked("hermes_clone");

    let CloneArgs {
        minified_map_path,
        composed_map_path,
        project,
        version,
    } = args;

    let minified_map = SourceMapFile::load(&minified_map_path).map_err(|e| {
        anyhow!(
            "Failed to load minfied map at '{}': {}",
            minified_map_path.display(),
            e
        )
    })?;

    let composed_map = SourceMapFile::load(&composed_map_path).map_err(|e| {
        anyhow!(
            "Failed to load composed map at '{}': {}",
            minified_map_path.display(),
            e
        )
    })?;

    let release_id = get_release_for_maps(minified_map_path, project, version, [&minified_map])?;

    // The flow here differs from plain sourcemap injection a bit - here, we don't ever
    // overwrite the chunk ID, because at this point in the build process, we no longer
    // control what chunk ID is inside the compiled hermes byte code bundle. So, instead,
    // we permit e.g. uploading the same chunk ID's to two different posthog envs with two
    // different release ID's, or arbitrarily re-running the upload command, but if someone
    // tries to run `clone` twice, changing release but not posthog env, we'll error out. The
    // correct way to upload the same set of artefacts to the same posthog env as part of
    // two different releases is, 1, not to, but failing that, 2, to re-run the bundling process
    if !minified_map.has_release_id() || minified_map.get_release_id() != release_id {
        minified_map.set_release_id(release_id.clone());
        minified_map.save()?;
    }

    // Copy metadata from source map to composed map
    if let Some(chunk_id) = minified_map.get_chunk_id() {
        composed_map.set_chunk_id(Some(chunk_id));
    }

    if let Some(release_id) = minified_map.get_release_id() {
        composed_map.set_release_id(Some(release_id));
    }

    composed_map.save()?;
    info!(
        "Successfully cloned metadata to {}",
        composed_map.inner.path.display()
    );

    info!("Finished cloning metadata");
    Ok(())
}
