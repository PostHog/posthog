use std::{fmt::Display, path::PathBuf};

use anyhow::{bail, Result};

use crate::{api::releases::ReleaseBuilder, utils::files::FileSelection};

#[derive(clap::Args, Clone)]
pub struct FileSelectionArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long, alias = "file")]
    pub directory: Vec<PathBuf>,

    /// One or more directory glob patterns to exclude from selection
    #[arg(short, long, alias = "ignore")]
    pub exclude: Vec<String>,

    /// One or more directory glob patterns to include in selection
    #[arg(short, long)]
    pub include: Vec<String>,
}

impl TryFrom<FileSelectionArgs> for FileSelection {
    type Error = anyhow::Error;
    fn try_from(args: FileSelectionArgs) -> Result<Self> {
        FileSelection::from_roots(args.directory)
            .include(args.include)?
            .exclude(args.exclude)
    }
}

impl Display for FileSelectionArgs {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}", self.directory)
    }
}

impl FileSelectionArgs {
    pub fn validate(&self) -> Result<()> {
        if self.directory.is_empty() {
            bail!("No --directory provided")
        }
        for dir in &self.directory {
            if !dir.exists() {
                bail!("{dir:?} does not exist");
            }
        }
        Ok(())
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

impl From<ReleaseArgs> for ReleaseBuilder {
    fn from(args: ReleaseArgs) -> Self {
        let mut builder = ReleaseBuilder::default();
        args.project
            .as_ref()
            .map(|project| builder.with_project(project));
        args.version
            .as_ref()
            .map(|version| builder.with_version(version));
        builder
    }
}
