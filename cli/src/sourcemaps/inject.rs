use anyhow::{anyhow, bail, Result};
use std::path::PathBuf;
use tracing::info;
use walkdir::DirEntry;

use crate::{
    api::releases::ReleaseBuilder, sourcemaps::source_pairs::read_pairs, utils::git::get_git_info,
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
    /// injection.
    #[arg(long)]
    pub version: Option<String>,
}

pub fn inject_impl(args: &InjectArgs, matcher: impl Fn(&DirEntry) -> bool) -> Result<()> {
    let InjectArgs {
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
    let mut pairs = read_pairs(&directory, ignore, matcher)?;
    if pairs.is_empty() {
        bail!("No source files found");
    }
    info!("Found {} pairs", pairs.len());

    // We need to fetch or create a release if: the user specified one, any pair is missing one, or the user
    // forced release overriding
    let needs_release =
        project.is_some() || version.is_some() || pairs.iter().any(|p| !p.has_release_id());

    let mut created_release = None;
    if needs_release {
        let mut builder = get_git_info(Some(directory))?
            .map(ReleaseBuilder::init_from_git)
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

    for pair in &mut pairs {
        let chunk_id = uuid::Uuid::now_v7().to_string();
        if let Some(previous_chunk_id) = pair.get_chunk_id() {
            pair.update_chunk_id(previous_chunk_id, chunk_id)?;
        } else {
            pair.add_chunk_id(chunk_id)?;
        }

        // If we've got a release, and the user asked us to, or a set is missing one,
        // put the release ID on the pair
        if !pair.has_release_id() {
            if let Some(release) = created_release.as_ref() {
                pair.set_release_id(release.id.to_string());
            }
        }
    }

    // Write the source and sourcemaps back to disk
    for pair in &pairs {
        pair.save()?;
    }
    info!("Finished processing directory");

    Ok(())
}
