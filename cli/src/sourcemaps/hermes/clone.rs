use std::path::PathBuf;

use anyhow::{anyhow, bail, Result};
use tracing::{info, warn};

use crate::{
    invocation_context::context,
    sourcemaps::{
        content::SourceMapFile,
        hermes::{get_composed_map, inject::is_metro_bundle},
        inject::get_release_for_pairs,
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
        directory,
        ignore,
        project,
        version,
    } = args;

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;

    info!("Processing directory: {}", directory.display());
    let pairs = read_pairs(&directory, ignore, is_metro_bundle, &None)?;

    if pairs.is_empty() {
        bail!("No source files found");
    }

    info!("Found {} pairs", pairs.len());

    let release_id =
        get_release_for_pairs(&directory, project, version, &pairs)?.map(|r| r.id.to_string());

    // The flow here differs from plain sourcemap injection a bit - here, we don't ever
    // overwrite the chunk ID, because at this point in the build process, we no longer
    // control what chunk ID is inside the compiled hermes byte code bundle. So, instead,
    // we permit e.g. uploading the same chunk ID's to two different posthog envs with two
    // different release ID's, or arbitrarily re-running the upload command, but if someone
    // tries to run `clone` twice, changing release but not posthog env, we'll error out. The
    // correct way to upload the same set of artefacts to the same posthog env as part of
    // two different releases is, 1, not to, but failing that, 2, to re-run the bundling process
    let mut pairs = pairs;
    for pair in &mut pairs {
        if !pair.has_release_id() || pair.get_release_id() != release_id {
            pair.set_release_id(release_id.clone());
            pair.save()?;
        }
    }
    let pairs = pairs;

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
            composed.set_chunk_id(Some(chunk_id));
        }

        if let Some(release_id) = minified.get_release_id() {
            composed.set_release_id(Some(release_id));
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
