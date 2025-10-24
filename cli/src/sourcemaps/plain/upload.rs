use std::path::PathBuf;

use anyhow::{Context, Result};
use tracing::{info, warn};

use crate::{
    api::symbol_sets::{self, SymbolSetUpload},
    invocation_context::context,
    sourcemaps::{plain::inject::is_javascript_file, source_pairs::read_pairs},
    utils::files::delete_files,
};

#[derive(clap::Args, Clone)]
pub struct Args {
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

    /// Whether to delete the source map files after uploading them
    #[arg(long, default_value = "false")]
    pub delete_after: bool,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,

    /// DEPRECATED: Does nothing. Set project during `inject` instead
    #[arg(long)]
    pub project: Option<String>,

    /// DEPRECATED: Does nothing. Set version during `inject` instead
    #[arg(long)]
    pub version: Option<String>,

    /// DEPRECATED - use top-level `--skip-ssl-verification` instead
    #[arg(long, default_value = "false")]
    pub skip_ssl_verification: bool,
}

pub fn upload_cmd(args: &Args) -> Result<()> {
    if args.project.is_some() || args.version.is_some() {
        warn!("`--project` and `--version` are deprecated and do nothing. Set project and version during `inject` instead.");
    }

    context().capture_command_invoked("sourcemap_upload");
    upload(args)
}

pub fn upload(args: &Args) -> Result<()> {
    if args.project.is_some() || args.version.is_some() {
        warn!("`--project` and `--version` are deprecated and do nothing. Set project and version during `inject` instead.");
    }

    let pairs = read_pairs(
        &args.directory,
        &args.ignore,
        is_javascript_file,
        &args.public_path_prefix,
    )?;
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

    symbol_sets::upload(&uploads, args.batch_size)?;

    if args.delete_after {
        delete_files(sourcemap_paths).context("While deleting sourcemaps")?;
    }

    Ok(())
}
