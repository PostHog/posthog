use std::{
    fmt::Display,
    io::{self, BufRead},
    num::NonZeroUsize,
    path::PathBuf,
};

use anyhow::{bail, Result};

use crate::{
    api::{releases::ReleaseBuilder, symbol_sets::DEFAULT_UPLOAD_CONCURRENCY},
    utils::files::FileSelection,
};

pub const SOURCEMAP_UPLOAD_CONCURRENCY_ENV: &str = "POSTHOG_CLI_SOURCEMAP_UPLOAD_CONCURRENCY";

#[derive(clap::Args, Clone, Debug)]
pub struct UploadConcurrencyArgs {
    /// The number of sourcemap files to upload concurrently
    #[arg(
        long,
        env = SOURCEMAP_UPLOAD_CONCURRENCY_ENV,
        default_value_t = DEFAULT_UPLOAD_CONCURRENCY
    )]
    pub concurrency: NonZeroUsize,
}

#[derive(clap::Args, Clone)]
pub struct FileSelectionArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long, alias = "file")]
    pub directory: Vec<PathBuf>,

    /// Read additional file/directory paths from stdin (one per line) [default: false]
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
    /// retry the upload without associating a release instead of failing. [default: true]
    #[arg(long, default_value = "true")]
    pub skip_release_on_fail: bool,
}

#[derive(clap::Args, Clone, Default)]
pub struct UploadConflictArgs {
    /// Allow overwriting an existing symbol set whose content has changed. [default: false]
    #[arg(long, default_value_t = false, conflicts_with = "skip_on_conflict")]
    pub force: bool,

    /// Skip symbol sets that already exist with different content instead of failing.
    /// Existing symbol sets are left unchanged. [default: false]
    #[arg(long, default_value_t = false, conflicts_with = "force")]
    pub skip_on_conflict: bool,
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
    use clap::Parser;
    use std::sync::Mutex;

    static CONCURRENCY_ENV_LOCK: Mutex<()> = Mutex::new(());

    #[derive(Debug, Parser)]
    struct ConcurrencyCli {
        #[command(flatten)]
        upload: UploadConcurrencyArgs,
    }

    fn parse_concurrency(args: &[&str], env: Option<&str>) -> clap::error::Result<ConcurrencyCli> {
        let _guard = CONCURRENCY_ENV_LOCK.lock().unwrap();
        let original = std::env::var_os(SOURCEMAP_UPLOAD_CONCURRENCY_ENV);

        match env {
            Some(value) => std::env::set_var(SOURCEMAP_UPLOAD_CONCURRENCY_ENV, value),
            None => std::env::remove_var(SOURCEMAP_UPLOAD_CONCURRENCY_ENV),
        }

        let parsed = ConcurrencyCli::try_parse_from(args);

        match original {
            Some(value) => std::env::set_var(SOURCEMAP_UPLOAD_CONCURRENCY_ENV, value),
            None => std::env::remove_var(SOURCEMAP_UPLOAD_CONCURRENCY_ENV),
        }

        parsed
    }

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

    #[test]
    fn upload_concurrency_defaults_to_ten() {
        let parsed = parse_concurrency(&["test"], None).unwrap();

        assert_eq!(parsed.upload.concurrency.get(), 10);
    }

    #[test]
    fn upload_concurrency_accepts_cli_override() {
        let parsed = parse_concurrency(&["test", "--concurrency", "32"], None).unwrap();

        assert_eq!(parsed.upload.concurrency.get(), 32);
    }

    #[test]
    fn upload_concurrency_accepts_environment_override() {
        let parsed = parse_concurrency(&["test"], Some("48")).unwrap();

        assert_eq!(parsed.upload.concurrency.get(), 48);
    }

    #[test]
    fn upload_concurrency_prefers_cli_override() {
        let parsed = parse_concurrency(&["test", "--concurrency", "32"], Some("48")).unwrap();

        assert_eq!(parsed.upload.concurrency.get(), 32);
    }

    #[test]
    fn upload_concurrency_rejects_zero_cli_value() {
        let error = parse_concurrency(&["test", "--concurrency", "0"], None).unwrap_err();

        assert!(error.to_string().contains("invalid value '0'"));
    }

    #[test]
    fn upload_concurrency_rejects_invalid_environment_values() {
        for value in ["0", "many"] {
            let error = parse_concurrency(&["test"], Some(value)).unwrap_err();
            let message = error.to_string();
            assert!(
                message.contains(&format!("invalid value '{value}'"))
                    && message.contains("--concurrency"),
                "unexpected error for {value:?}: {message}"
            );
        }
    }

    /// Golden vectors pinning the release `hash_id` the CLI writes: `content_hash([name, version])`
    /// with `version = pack_version(version, build)` (see `api::releases::create_release`). Cymbal
    /// reconstructs the same hash from a mobile event's app metadata (`mobile_release_hash_id` in
    /// `rust/cymbal/src/core/types/frames/releases.rs`), so these literals must stay identical on
    /// both sides or mobile releases silently stop resolving. Keep in sync with the matching golden
    /// test in cymbal.
    #[test]
    fn release_hash_id_golden_vectors() {
        use crate::utils::files::content_hash;

        // (name, version, build, expected hash_id)
        let cases: [(&str, Option<&str>, Option<&str>, &str); 4] = [
            (
                "com.posthog.iosraw",
                Some("1.0"),
                Some("1"),
                "75605cac5268ba4bdc57b4c8336f6686802e88236ae4026418a18cabcde854d1015f18734489b8ec4c71c68773a027e5b880f7278b8ba6864a5334d76ef9eba6",
            ),
            (
                "com.example.app",
                Some("1.0"),
                Some("42"),
                "5a7f7b504d81759fa4e15f8b3bbc77c694a9dc222cfcd06c801fae9619076e97909edf651087106af331aea76463449f015ccc41ccacbf19148329b1c2c35aa7",
            ),
            (
                "com.example.app",
                Some("2.3"),
                None,
                "09aeeb69b914985562d4aa39d13033abf0f90c753ef90b0148cb06b8aeadca7dd1dd853fa24c7cc51d18cf251bb7348eae58906347a217a98d74ba7ca5673b66",
            ),
            (
                "com.example.app",
                None,
                Some("99"),
                "5e925a3f2e9349f64ab88eede466b641a7332dc79d6f1901d931fb659704a0475fa77a3ca25c0a60b2919547de8d94117fbcc52448e83aa72787a3fe35f725ae",
            ),
        ];

        for (name, version, build, expected) in cases {
            let version = version.map(String::from);
            let build = build.map(String::from);
            let packed = pack_version(&version, &build).expect("these cases always pack a version");
            let hash_id = content_hash([name.as_bytes(), packed.as_bytes()]);
            assert_eq!(
                hash_id, expected,
                "release hash_id drift for {name} {version:?}+{build:?}"
            );
        }
    }
}
