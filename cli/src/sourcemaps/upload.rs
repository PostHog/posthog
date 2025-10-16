use std::path::PathBuf;

use anyhow::{Context, Ok, Result};
use tracing::info;

use crate::api::symbol_sets::{upload, SymbolSetUpload};
use crate::invocation_context::context;

use crate::sourcemaps::source_pair::read_pairs;
use crate::utils::files::delete_files;

#[derive(clap::Args, Clone)]
pub struct UploadArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    pub ignore: Vec<String>,

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
        ignore,
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

    let uploads = pairs
        .into_iter()
        .map(TryInto::try_into)
        .collect::<Result<Vec<SymbolSetUpload>>>()
        .context("While preparing files for upload")?;

    upload(&uploads, batch_size)?;

    if delete_after {
        delete_files(sourcemap_paths).context("While deleting sourcemaps")?;
    }

    Ok(())
}
