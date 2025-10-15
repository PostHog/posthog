use anyhow::{anyhow, bail, Ok, Result};
use std::path::PathBuf;
use tracing::info;
use uuid;

use crate::{
    api::releases::ReleaseBuilder, invocation_context::context,
    sourcemaps::source_pair::read_pairs, utils::git::get_git_info,
};

#[derive(clap::Args)]
pub struct InjectArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    pub ignore: Vec<String>,

    /// The project name associated with the uploaded chunks. Required to have the uploaded chunks associated with
    /// a specific release. We will try to auto-derive this from git information if not provided. Strongly recommended
    /// to be set explicitly during release CD workflows
    #[arg(long)]
    pub project: Option<String>,

    /// The version of the project - this can be a version number, semantic version, or a git commit hash. Required
    /// to have the uploaded chunks associated with a specific release. Overrides release information set during
    /// injection. Strongly prefer setting release information during injection.
    #[arg(long)]
    pub version: Option<String>,

    /// Force injection. This will override any existing chunk or release information already in the sourcemaps.
    #[arg(long, default_value = "false")]
    pub force: bool,
}

pub fn inject(args: &InjectArgs) -> Result<()> {
    let InjectArgs {
        directory,
        ignore,
        project,
        version,
        force,
    } = args;

    context().capture_command_invoked("sourcemap_inject");

    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;

    info!("Processing directory: {}", directory.display());
    let mut pairs = read_pairs(&directory, ignore)?;
    if pairs.is_empty() {
        bail!("No source files found");
    }
    info!("Found {} pairs", pairs.len());

    // We need to fetch or create a release if: the user specified one, any pair is missing one, or the user
    // forced release overriding
    let needs_release = project.is_some()
        || version.is_some()
        || pairs.iter().any(|p| !p.has_release_id())
        || *force;

    let mut created_release = None;
    if needs_release {
        let mut builder = get_git_info(Some(directory))?
            .map(|g| ReleaseBuilder::init_from_git(g))
            .unwrap_or_default();

        if let Some(project) = project {
            builder.with_project(project);
        }
        if let Some(version) = version {
            builder.with_version(version);
        }

        if builder.can_create() {
            created_release = Some(builder.fetch_or_create()?);
        }
    }

    let mut skipped_pairs = 0;
    for pair in &mut pairs {
        if pair.has_chunk_id() && !force {
            skipped_pairs += 1;
            continue;
        }
        let chunk_id = uuid::Uuid::now_v7().to_string();
        pair.set_chunk_id(chunk_id)?;

        // If we've got a release, and the user asked us to, or a set is missing one,
        // put the release ID on the pair
        if created_release.is_some() && (*force || !pair.has_release_id()) {
            pair.set_release_id(created_release.as_ref().unwrap().id.to_string());
        }
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

    Ok(())
}
