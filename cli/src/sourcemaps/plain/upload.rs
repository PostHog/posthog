use anyhow::{Context, Result};
use tracing::info;

use crate::{
    api::symbol_sets::{self, SymbolSetUpload},
    invocation_context::context,
    sourcemaps::{
        args::{FileSelectionArgs, ReleaseArgs},
        plain::inject::is_javascript_file,
        source_pairs::read_pairs,
    },
    utils::files::{delete_files, FileSelection},
};

#[derive(clap::Args, Clone)]
pub struct Args {
    #[clap(flatten)]
    pub file_selection: FileSelectionArgs,

    /// If your bundler adds a public path prefix to sourcemap URLs,
    /// we need to ignore it while searching for them
    /// For use alongside e.g. esbuilds "publicPath" config setting.
    #[arg(short, long)]
    pub public_path_prefix: Option<String>,

    /// Whether to delete the source map files after uploading them
    #[arg(long, default_value = "false")]
    pub delete_after: bool,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,

    #[clap(flatten)]
    pub release: ReleaseArgs,

    /// DEPRECATED - use top-level `--skip-ssl-verification` instead
    #[arg(long, default_value = "false")]
    pub skip_ssl_verification: bool,
}

pub fn upload_cmd(args: &Args) -> Result<()> {
    args.file_selection.validate()?;
    context().capture_command_invoked("sourcemap_upload");
    upload(args)
}

pub fn upload(args: &Args) -> Result<()> {
    let selection = FileSelection::try_from(args.file_selection.clone())?;

    let pairs = read_pairs(
        selection.into_iter().filter(is_javascript_file),
        &args.public_path_prefix,
    );

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
