use std::path::PathBuf;

use anyhow::{anyhow, Result};

use crate::{
    api::{self, releases::ReleaseBuilder, symbol_sets::SymbolSetUpload},
    proguard::ProguardFile,
    utils::git::get_git_info,
};

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The location of the file to upload
    #[arg(short, long)]
    pub path: PathBuf,

    /// This is the identifier posthog will use to look up with mapping file, when it's processing your
    /// stack traces. Must match with the identifier provided to the posthog SDK at runtime, for this build.
    #[arg(short, long)]
    pub map_id: String,

    /// The project name associated with this build. Required to have the exceptions associated with
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

pub fn upload(args: &Args) -> Result<()> {
    let Args {
        path,
        map_id,
        project,
        version,
    } = args;

    let path = path
        .canonicalize()
        .map_err(|e| anyhow!("Path {} canonicalization failed: {}", path.display(), e))?;
    let directory = path
        .parent()
        .ok_or_else(|| anyhow!("Could not get path parent"))?;

    let mut release_builder = get_git_info(Some(directory.to_path_buf()))?
        .map(ReleaseBuilder::init_from_git)
        .unwrap_or_default();

    if let Some(project) = project {
        release_builder.with_project(project);
    }
    if let Some(version) = version {
        release_builder.with_version(version);
    }

    let mut file = ProguardFile::new(&path, map_id.clone())?;

    let release = release_builder
        .can_create()
        .then(|| release_builder.fetch_or_create())
        .transpose()?;

    file.release_id = release.map(|r| r.id.to_string());

    let to_upload: SymbolSetUpload = file.try_into()?;

    api::symbol_sets::upload(&[to_upload], 50)?;

    // Your upload logic here
    Ok(())
}
