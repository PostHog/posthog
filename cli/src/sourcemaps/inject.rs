use anyhow::{anyhow, bail, Ok, Result};
use std::path::PathBuf;
use tracing::info;
use uuid;

use crate::{
    api::releases::{Release, ReleaseBuilder},
    invocation_context::context,
    sourcemaps::source_pair::read_pairs,
    utils::git::get_git_info,
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
}

pub fn inject(args: &InjectArgs) -> Result<()> {
    let InjectArgs {
        directory,
        ignore,
        project,
        version,
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

    let mut skipped_pairs = 0;

    let explicit_release = project.is_some() && version.is_some();

    // We need a release ID to put on the pairs if either the user is explicitly specifying one,
    // or if any of the pairs don't have one already set.
    let needs_release = explicit_release || pairs.iter().any(|p| !p.has_release_id());

    let mut created_release = None;
    if needs_release {
        if project.is_some() && version.is_some() {
            created_release = Some(Release::fetch_or_create(
                project.as_ref().unwrap(),
                version.as_ref().unwrap(),
                Some(directory.clone()),
            )?)
        } else if let Some(git_info) = get_git_info(Some(directory.clone()))? {
            let builder = ReleaseBuilder::init_from_git(git_info);
            if builder.can_create() {
                created_release = Some(builder.create_release()?);
            }
        }
    }

    for pair in &mut pairs {
        if pair.has_chunk_id() {
            skipped_pairs += 1;
            continue;
        }
        let chunk_id = uuid::Uuid::now_v7().to_string();
        pair.set_chunk_id(chunk_id)?;

        // If we've got a release, and the user asked us to, or a set is missing one,
        // put the release ID on the pair
        if created_release.is_some() && (explicit_release || !pair.has_release_id()) {
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
