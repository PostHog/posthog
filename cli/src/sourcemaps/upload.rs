use std::path::PathBuf;

use anyhow::{Context, Ok, Result};
use tracing::info;

use crate::api::symbol_sets::{upload, SymbolSetUpload};
use crate::invocation_context::context;

use crate::releases::{Release, ReleaseBuilder};
use crate::sourcemaps::source_pair::read_pairs;
use crate::utils::files::delete_files;
use crate::utils::git::get_git_info;

#[derive(clap::Args, Clone)]
pub struct UploadArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    pub ignore: Vec<String>,

    /// The project name associated with the uploaded chunks. Required to have the uploaded chunks associated with
    /// a specific release. Overrides release information set during injection. Strongly prefer setting release
    /// information during injection, as otherwise repeated invocations of the upload command will fail.
    #[arg(long)]
    pub project: Option<String>,

    /// The version of the project - this can be a version number, semantic version, or a git commit hash. Required
    /// to have the uploaded chunks associated with a specific release. Overrides release information set during
    /// injection. Strongly prefer setting release information during injection, as otherwise repeated invocations
    /// of the upload command will fail.
    #[arg(long)]
    pub version: Option<String>,

    /// Whether to delete the source map files after uploading them
    #[arg(long, default_value = "false")]
    pub delete_after: bool,

    /// Whether to skip SSL verification when uploading chunks - only use when using self-signed certificates for
    /// self-deployed instances
    #[arg(long, default_value = "false")]
    pub skip_ssl_verification: bool,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,
}

pub fn upload_cmd(args: UploadArgs) -> Result<()> {
    let UploadArgs {
        directory,
        project,
        ignore,
        version,
        delete_after,
        skip_ssl_verification: _,
        batch_size,
    } = args;

    context().capture_command_invoked("sourcemap_upload");

    let pairs = read_pairs(&directory, &ignore)?;
    let sourcemap_paths = pairs
        .iter()
        .map(|pair| pair.sourcemap.inner.path.clone())
        .collect::<Vec<_>>();
    info!("Found {} chunks to upload", pairs.len());

    let mut uploads = pairs
        .into_iter()
        .map(TryInto::try_into)
        .collect::<Result<Vec<SymbolSetUpload>>>()
        .context("While preparing files for upload")?;

    // If the user wants to override the injected release info, let them
    if project.is_some() && version.is_some() {
        let (project, version) = (project.unwrap(), version.unwrap());

        // Either fetch an existing release, or create one
        if let Some(existing) = Release::lookup(&project, &version)? {
            uploads
                .iter_mut()
                .for_each(|e| e.release_id = Some(existing.id.to_string()));
        } else {
            let mut builder = ReleaseBuilder::default();
            if let Some(info) = get_git_info(Some(directory.clone()))? {
                builder.with_git(info);
            }
            builder.with_version(&version).with_project(&project);
            let created = builder.create_release()?;
            uploads
                .iter_mut()
                .for_each(|e| e.release_id = Some(created.id.to_string()));
        }
    }

    upload(&uploads, batch_size)?;

    if delete_after {
        delete_files(sourcemap_paths).context("While deleting sourcemaps")?;
    }

    Ok(())
}
