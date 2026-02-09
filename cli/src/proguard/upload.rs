use std::path::PathBuf;

use anyhow::{anyhow, Result};

use crate::{
    api::{self, releases::ReleaseBuilder, symbol_sets::SymbolSetUpload},
    proguard::ProguardFile,
    sourcemaps::args::ReleaseArgs,
    utils::git::get_git_info,
};

#[derive(clap::Args, Clone)]
pub struct Args {
    /// The location of the proguard mapping file to upload.
    #[arg(short, long)]
    pub path: PathBuf,

    /// This is the identifier posthog will use to look up with mapping file, when it's processing your
    /// stack traces. Must match with the identifier provided to the posthog SDK at runtime, for this build.
    #[arg(short, long)]
    pub map_id: String,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,

    #[clap(flatten)]
    pub release: ReleaseArgs,
}

pub fn upload(args: &Args) -> Result<()> {
    let Args {
        path,
        map_id,
        batch_size,
        release,
    } = args;

    let ReleaseArgs {
        project,
        version,
        skip_release_on_fail,
    } = release;

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

    api::symbol_sets::upload_with_retry(vec![to_upload], *batch_size, *skip_release_on_fail)?;

    Ok(())
}
