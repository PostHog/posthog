use std::path::PathBuf;

use clap::Subcommand;

use crate::sourcemaps::inject::InjectArgs;

pub mod inject;
pub mod upload;

#[derive(Subcommand)]
pub enum SourcemapCommand {
    /// Inject each bundled chunk with a posthog chunk ID
    Inject(InjectArgs),
    /// Upload the bundled chunks to PostHog
    Upload(upload::Args),
    /// Run inject and upload in one command
    Process(ProcessArgs),
}

#[derive(clap::Args)]
pub struct ProcessArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    pub ignore: Vec<String>,

    /// If your bundler adds a public path prefix to sourcemap URLs,
    /// we need to ignore it while searching for them
    /// For use alongside e.g. esbuilds "publicPath" config setting.
    #[arg(short, long)]
    pub public_path_prefix: Option<String>,

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

    /// Whether to delete the source map files after uploading them
    #[arg(long, default_value = "false")]
    pub delete_after: bool,

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    pub batch_size: usize,
}

impl From<ProcessArgs> for (InjectArgs, upload::Args) {
    fn from(args: ProcessArgs) -> Self {
        let inject_args = InjectArgs {
            directory: args.directory.clone(),
            ignore: args.ignore.clone(),
            project: args.project,
            version: args.version,
            public_path_prefix: args.public_path_prefix.clone(),
        };
        let upload_args = upload::Args {
            directory: args.directory,
            public_path_prefix: args.public_path_prefix,
            ignore: args.ignore,
            delete_after: args.delete_after,
            skip_ssl_verification: false,
            batch_size: args.batch_size,
            project: None,
            version: None,
        };

        (inject_args, upload_args)
    }
}
