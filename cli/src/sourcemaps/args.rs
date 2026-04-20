use std::{
    fmt::Display,
    io::{self, BufRead},
    path::PathBuf,
};

use anyhow::{bail, Result};

use crate::{api::releases::ReleaseBuilder, utils::files::FileSelection};

#[derive(clap::Args, Clone)]
pub struct FileSelectionArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long, alias = "file")]
    pub directory: Vec<PathBuf>,

    /// Read additional file/directory paths from stdin (one per line)
    #[arg(long, default_value = "false")]
    pub stdin: bool,

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
        let args = args.resolve_stdin()?;
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
        if self.directory.is_empty() && !self.stdin {
            bail!("No --directory provided")
        }
        for dir in &self.directory {
            if !dir.exists() {
                bail!("{dir:?} does not exist");
            }
        }
        Ok(())
    }

    /// Read stdin paths (if `--stdin` was set) and fold them into `directory`,
    /// returning a new `FileSelectionArgs` that no longer needs stdin.
    /// This allows the resolved args to be cloned and reused by multiple
    /// downstream consumers (e.g. inject + upload in the `process` command).
    pub fn resolve_stdin(mut self) -> Result<Self> {
        if self.stdin {
            let stdin = io::stdin();
            for line in stdin.lock().lines() {
                let line = line?;
                let trimmed = line.trim();
                if !trimmed.is_empty() {
                    self.directory.push(PathBuf::from(trimmed));
                }
            }
            self.stdin = false;
        }
        Ok(self)
    }
}

#[derive(clap::Args, Clone)]
pub struct ReleaseArgs {
    /// The project name associated with the uploaded chunks. Required to have the uploaded chunks associated with
    /// a specific release. We will try to auto-derive this from git information if not provided. Strongly recommended
    /// to be set explicitly during release CD workflows
    #[arg(long = "release-name", alias = "project")]
    // deprecated alias for backwards compatibility
    pub name: Option<String>,

    /// The version of the project - this can be a version number, semantic version, or a git commit hash. Required
    /// to have the uploaded chunks associated with a specific release. We will try to auto-derive this from git information
    /// if not provided.
    #[arg(long = "release-version", alias = "version")]
    // deprecated alias for backwards compatibility
    pub version: Option<String>,

    /// The build number (e.g., 42, CFBundleVersion on iOS, versionCode on Android).
    /// Stored as release metadata. Optional — when omitted, no build info is recorded.
    #[arg(long)]
    pub build: Option<String>,

    /// If the server returns a release_id_mismatch error (symbol set already exists with a different release),
    /// retry the upload without associating a release instead of failing.
    #[arg(long, default_value = "true")]
    pub skip_release_on_fail: bool,
}

/// Pack version and build into a single string for release uniqueness.
/// Releases are keyed on (name, version), so "1.0+42" and "1.0+43" are
/// distinct releases. The UI splits on "+" to display them separately.
pub fn pack_version(version: &Option<String>, build: &Option<String>) -> Option<String> {
    match (version, build) {
        (Some(v), Some(b)) => Some(format!("{v}+{b}")),
        (Some(v), None) => Some(v.clone()),
        (None, Some(b)) => Some(b.clone()),
        (None, None) => None,
    }
}

impl From<ReleaseArgs> for ReleaseBuilder {
    fn from(args: ReleaseArgs) -> Self {
        let mut builder = ReleaseBuilder::default();
        args.name.as_ref().map(|project| builder.with_name(project));
        pack_version(&args.version, &args.build)
            .as_ref()
            .map(|version| builder.with_version(version));
        builder
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_args(name: Option<&str>, version: Option<&str>, build: Option<&str>) -> ReleaseArgs {
        ReleaseArgs {
            name: name.map(String::from),
            version: version.map(String::from),
            build: build.map(String::from),
            skip_release_on_fail: true,
        }
    }

    #[test]
    fn release_args_to_builder() {
        let cases: Vec<(Option<&str>, Option<&str>, bool)> = vec![
            // (version,    build,      has_version)
            (Some("1.0"), None, true),       // version only
            (Some("1.0"), Some("42"), true), // version+build packed into "1.0+42"
            (None, Some("42"), true),        // build-only → version="42"
            (None, None, false),             // neither
        ];

        for (version, build, expect_version) in cases {
            let builder: ReleaseBuilder = make_args(Some("com.app"), version, build).into();
            assert!(builder.has_name(), "name should always be set");
            assert_eq!(
                builder.has_version(),
                expect_version,
                "version={version:?} build={build:?}"
            );
        }
    }
}
