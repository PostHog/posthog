use anyhow::{bail, Context, Result};
use std::path::Path;
use tracing::{info, warn};
use walkdir::DirEntry;

use crate::{
    api::releases::{Release, ReleaseBuilder},
    sourcemaps::{
        args::{FileSelectionArgs, ReleaseArgs},
        content::SourceMapFile,
        source_pairs::{read_pairs, SourcePair},
    },
    utils::{files::FileSelection, git::get_git_info},
};

#[derive(clap::Args)]
pub struct InjectArgs {
    #[clap(flatten)]
    pub file_selection: FileSelectionArgs,

    /// If your bundler adds a public path prefix to sourcemap URLs,
    /// we need to ignore it while searching for them
    /// For use alongside e.g. esbuilds "publicPath" config setting.
    #[arg(short, long)]
    pub public_path_prefix: Option<String>,

    #[clap(flatten)]
    pub release: ReleaseArgs,
}

impl InjectArgs {
    pub fn validate(&self) -> Result<()> {
        self.file_selection.validate()
    }
}

pub fn inject_impl(
    args: &InjectArgs,
    matcher: impl Fn(&DirEntry) -> bool + 'static,
    existing_release: Option<&Release>,
) -> Result<()> {
    let InjectArgs {
        file_selection,
        public_path_prefix,
        release,
    } = args;

    info!("injecting selection: {}", file_selection);

    let iterator = FileSelection::try_from(file_selection.clone())?;

    let mut pairs = read_pairs(
        iterator.into_iter().filter(|entry| matcher(entry)),
        public_path_prefix,
    );
    if pairs.is_empty() {
        bail!("no source files found");
    }

    let created_release_id = if let Some(r) = existing_release {
        Some(r.id.to_string())
    } else {
        let cwd = std::env::current_dir()?;
        get_release_for_maps(&cwd, release.clone(), pairs.iter().map(|p| &p.sourcemap))?
            .as_ref()
            .map(|r| r.id.to_string())
    };

    pairs = inject_pairs(pairs, created_release_id)?;

    // Write the source and sourcemaps back to disk
    for pair in &pairs {
        pair.save()?;
    }
    info!("injecting done");
    Ok(())
}

pub fn inject_pairs(
    mut pairs: Vec<SourcePair>,
    created_release_id: Option<String>,
) -> Result<Vec<SourcePair>> {
    for pair in &mut pairs {
        let current_release_id = pair.get_release_id();
        // We only update release ids and chunk ids when the release id changed or is not present
        if current_release_id != created_release_id || pair.get_chunk_id().is_none() {
            pair.set_release_id(created_release_id.clone());

            let chunk_id = uuid::Uuid::now_v7().to_string();
            if let Some(previous_chunk_id) = pair.get_chunk_id() {
                pair.update_chunk_id(previous_chunk_id, chunk_id)?;
            } else {
                pair.add_chunk_id(chunk_id)?;
            }
        }
    }

    Ok(pairs)
}

pub fn get_release_for_maps<'a>(
    directory: &Path,
    release: ReleaseArgs,
    maps: impl IntoIterator<Item = &'a SourceMapFile>,
) -> Result<Option<Release>> {
    // We need to fetch or create a release if: the user specified one, any pair is missing one, or the user
    // forced release overriding
    let needs_release = release.name.is_some()
        || release.version.is_some()
        || release.build.is_some()
        || maps.into_iter().any(|p| !p.has_release_id());

    let mut created_release = None;
    if needs_release {
        let release_args_were_provided =
            release.name.is_some() || release.version.is_some() || release.build.is_some();
        let mut builder: ReleaseBuilder = release.into();

        add_git_info_to_release_builder(directory, &mut builder, release_args_were_provided)?;

        if builder.can_create() {
            created_release = Some(builder.fetch_or_create()?);
        }
    }

    Ok(created_release)
}

fn add_git_info_to_release_builder(
    directory: &Path,
    builder: &mut ReleaseBuilder,
    release_args_were_provided: bool,
) -> Result<()> {
    let needs_git_for_release_fields = !builder.can_create();

    match get_git_info(Some(directory.to_path_buf())) {
        Ok(Some(info)) => {
            builder.with_git(info);
        }
        Ok(None) if needs_git_for_release_fields && release_args_were_provided => {
            anyhow::bail!(
                "Release fields are incomplete and git info is unavailable. Provide both --release-name and --release-version, or run from a git repository or supported CI environment."
            );
        }
        Ok(None) => {}
        Err(error) if needs_git_for_release_fields => {
            return Err(error).context("Failed to determine git info for release");
        }
        Err(error) => {
            warn!("Skipping git metadata after failing to determine git info: {error:#}");
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        sync::{Mutex, MutexGuard},
    };

    use super::*;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    const GIT_INFO_ENV_VARS: &[&str] = &[
        "GITHUB_ACTIONS",
        "GITHUB_SHA",
        "GITHUB_REF_NAME",
        "GITHUB_REPOSITORY",
        "GITHUB_SERVER_URL",
        "VERCEL",
        "VERCEL_GIT_PROVIDER",
        "VERCEL_GIT_REPO_OWNER",
        "VERCEL_GIT_REPO_SLUG",
        "VERCEL_GIT_COMMIT_REF",
        "VERCEL_GIT_COMMIT_SHA",
    ];

    fn lock_env() -> MutexGuard<'static, ()> {
        ENV_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn remove_env_vars(names: &[&str]) -> Vec<(String, Option<String>)> {
        names
            .iter()
            .map(|name| {
                let value = std::env::var(name).ok();
                std::env::remove_var(name);
                ((*name).to_string(), value)
            })
            .collect()
    }

    struct EnvVarGuard(Vec<(String, Option<String>)>);

    impl EnvVarGuard {
        fn clear(names: &[&str]) -> Self {
            Self(remove_env_vars(names))
        }
    }

    impl Drop for EnvVarGuard {
        fn drop(&mut self) {
            for (name, value) in self.0.drain(..) {
                match value {
                    Some(value) => std::env::set_var(name, value),
                    None => std::env::remove_var(name),
                }
            }
        }
    }

    fn release_args(name: Option<&str>, version: Option<&str>) -> ReleaseArgs {
        release_args_with_build(name, version, None)
    }

    fn release_args_with_build(
        name: Option<&str>,
        version: Option<&str>,
        build: Option<&str>,
    ) -> ReleaseArgs {
        ReleaseArgs {
            name: name.map(String::from),
            version: version.map(String::from),
            build: build.map(String::from),
            skip_release_on_fail: true,
        }
    }

    fn make_git_repo_without_branch_ref() -> tempfile::TempDir {
        let temp_root = tempfile::tempdir().expect("failed to create temporary repo");
        let git_dir = temp_root.path().join(".git");

        fs::create_dir_all(&git_dir).expect("failed to create .git directory");
        fs::write(git_dir.join("HEAD"), "ref: refs/heads/main\n").expect("failed to write HEAD");

        temp_root
    }

    #[test]
    fn git_failure_is_not_fatal_when_release_fields_are_explicit() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = make_git_repo_without_branch_ref();
        let mut builder: ReleaseBuilder = release_args(Some("my-app"), Some("1.0.0")).into();

        let result = add_git_info_to_release_builder(temp_root.path(), &mut builder, true);

        assert!(result.is_ok());
        assert!(builder.can_create());
    }

    #[test]
    fn git_failure_is_fatal_when_release_fields_need_git() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = make_git_repo_without_branch_ref();
        let mut builder: ReleaseBuilder = release_args(Some("my-app"), None).into();

        let error = add_git_info_to_release_builder(temp_root.path(), &mut builder, true)
            .expect_err("git failure should remain fatal when release fields are incomplete");

        assert!(format!("{error:#}").contains("Failed to determine git info for release"));
    }

    #[test]
    fn missing_git_is_not_fatal_for_best_effort_release_creation() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = tempfile::tempdir().expect("failed to create temporary directory");
        let mut builder: ReleaseBuilder = release_args(None, None).into();

        let result = add_git_info_to_release_builder(temp_root.path(), &mut builder, false);

        assert!(result.is_ok());
        assert!(!builder.can_create());
    }

    #[test]
    fn missing_git_is_fatal_when_release_args_are_incomplete() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = tempfile::tempdir().expect("failed to create temporary directory");
        let mut builder: ReleaseBuilder = release_args(Some("my-app"), None).into();

        let error = add_git_info_to_release_builder(temp_root.path(), &mut builder, true)
            .expect_err("missing git should be fatal when release args are incomplete");

        assert!(format!("{error:#}").contains("Release fields are incomplete"));
    }

    #[test]
    fn build_only_release_args_need_git() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = tempfile::tempdir().expect("failed to create temporary directory");

        let error = get_release_for_maps(
            temp_root.path(),
            release_args_with_build(None, None, Some("42")),
            std::iter::empty::<&SourceMapFile>(),
        )
        .expect_err("build-only release args should need git to fill the release name");

        assert!(format!("{error:#}").contains("Release fields are incomplete"));
    }
}
