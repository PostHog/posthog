use clap::Subcommand;
use core::str;
use std::path::PathBuf;

pub mod constant;
pub mod inject;
pub mod source_pair;
pub mod upload;

use crate::sourcemaps::inject::InjectArgs;
use crate::sourcemaps::upload::UploadArgs;

#[derive(clap::Args)]
pub struct ProcessArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    pub ignore: Vec<String>,

    /// The project name associated with the uploaded chunks. Required to have the uploaded chunks associated with
    /// a specific release. We will try to auto-derive this from git information if not provided. Strongly recommended
    /// to be set explicitly during release CD workflows.
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

#[derive(Subcommand)]
pub enum SourcemapCommand {
    /// Inject each bundled chunk with a posthog chunk ID
    Inject(InjectArgs),
    /// Upload the bundled chunks to PostHog
    Upload(UploadArgs),
    /// Run inject and upload in one command
    Process(ProcessArgs),
}

impl From<ProcessArgs> for (InjectArgs, UploadArgs) {
    fn from(args: ProcessArgs) -> Self {
        let inject_args = InjectArgs {
            directory: args.directory.clone(),
            ignore: args.ignore.clone(),
            project: args.project,
            version: args.version,
            force: args.force,
        };

        let upload_args = UploadArgs {
            directory: args.directory,
            ignore: args.ignore,
            delete_after: args.delete_after,
            skip_ssl_verification: args.skip_ssl_verification,
            batch_size: args.batch_size,
        };

        (inject_args, upload_args)
    }
}
