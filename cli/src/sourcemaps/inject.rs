use anyhow::{anyhow, bail, Result};
use std::path::{Path, PathBuf};
use tracing::info;
use walkdir::DirEntry;

use crate::{
    api::releases::{Release, ReleaseBuilder},
    sourcemaps::source_pairs::{read_pairs, SourcePair},
    utils::git::get_git_info,
};

#[derive(clap::Args)]
pub struct InjectArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// If your bundler adds a public path prefix to sourcemap URLs,
    /// we need to ignore it while searching for them
    /// For use alongside e.g. esbuilds "publicPath" config setting.
    #[arg(short, long)]
    pub public_path_prefix: Option<String>,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    pub ignore: Vec<String>,

    /// The project name associated with the uploaded chunks. Required to have the uploaded chunks associated with
    /// a specific release. We will try to auto-derive this from git information if not provided. Strongly recommended
    /// to be set explicitly during release CD workflows
    #[arg(long)]
    pub project: Option<String>,

    /// The version of the project - this can be a version number, semantic version, or a git commit hash. Required
    /// to have the uploaded chunks associated with a specific release. We will try to auto-derive this from git information
    /// if not provided.
    #[arg(long)]
    pub version: Option<String>,
}

pub fn inject_impl(args: &InjectArgs, matcher: impl Fn(&DirEntry) -> bool) -> Result<()> {
    let InjectArgs {
        directory,
        public_path_prefix,
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

    info!("injecting directory: {}", directory.display());
    let mut pairs = read_pairs(&directory, ignore, matcher, public_path_prefix)?;
    if pairs.is_empty() {
        bail!("no source files found");
    }

    let created_release_id = get_release_for_pairs(&directory, project, version, &pairs)?
        .as_ref()
        .map(|r| r.id.to_string());

    pairs = inject_pairs(pairs, created_release_id)?;

    // Write the source and sourcemaps back to disk
    for pair in &pairs {
        pair.save()?;
    }
    info!("injecting done");
    Ok(())
}

pub fn inject_pairs(
    mut pairs: Vec<SourcePair>,
    created_release_id: Option<String>,
) -> Result<Vec<SourcePair>> {
    for pair in &mut pairs {
        let current_release_id = pair.get_release_id();
        // We only update release ids and chunk ids when the release id changed or is not present
        if current_release_id != created_release_id || pair.get_chunk_id().is_none() {
            pair.set_release_id(created_release_id.clone());

            let chunk_id = uuid::Uuid::now_v7().to_string();
            if let Some(previous_chunk_id) = pair.get_chunk_id() {
                pair.update_chunk_id(previous_chunk_id, chunk_id)?;
            } else {
                pair.add_chunk_id(chunk_id)?;
            }
        }
    }

    Ok(pairs)
}

pub fn get_release_for_pairs<'a>(
    directory: &Path,
    project: &Option<String>,
    version: &Option<String>,
    pairs: impl IntoIterator<Item = &'a SourcePair>,
) -> Result<Option<Release>> {
    // We need to fetch or create a release if: the user specified one, any pair is missing one, or the user
    // forced release overriding
    let needs_release =
        project.is_some() || version.is_some() || pairs.into_iter().any(|p| !p.has_release_id());

    let mut created_release = None;
    if needs_release {
        let mut builder = get_git_info(Some(directory.to_path_buf()))?
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

    Ok(created_release)
}
