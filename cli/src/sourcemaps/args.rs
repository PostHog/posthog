use std::path::PathBuf;

use crate::utils::files::FileSelection;

#[derive(clap::Args, Clone)]
pub struct FileSelectionArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    pub directory: PathBuf,

    /// One or more directory glob patterns to exclude from selection
    #[arg(short, long, alias = "ignore")]
    pub exclude: Vec<String>,

    /// One or more directory glob patterns to include in selection
    #[arg(short, long)]
    pub include: Vec<String>,
}

impl From<FileSelectionArgs> for FileSelection {
    fn from(args: FileSelectionArgs) -> Self {
        FileSelection::new(args.directory, args.include, args.exclude)
    }
}

#[derive(clap::Args, Clone)]
pub struct ReleaseArgs {
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
