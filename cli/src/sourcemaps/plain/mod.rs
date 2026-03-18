use clap::Subcommand;

use crate::sourcemaps::{
    args::{FileSelectionArgs, ReleaseArgs},
    inject::InjectArgs,
};

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
    #[clap(flatten)]
    pub file_selection: FileSelectionArgs,

    /// If your bundler adds a public path prefix to sourcemap URLs,
    /// we need to ignore it while searching for them
    /// For use alongside e.g. esbuilds "publicPath" config setting.
    #[arg(short, long)]
    pub public_path_prefix: Option<String>,

    #[clap(flatten)]
    pub release: ReleaseArgs,

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
            file_selection: args.file_selection.clone(),
            release: args.release.clone(),
            public_path_prefix: args.public_path_prefix.clone(),
        };
        let upload_args = upload::Args {
            file_selection: args.file_selection,
            public_path_prefix: args.public_path_prefix,
            delete_after: args.delete_after,
            skip_ssl_verification: false,
            batch_size: args.batch_size,
            release: args.release,
        };

        (inject_args, upload_args)
    }
}
