use anyhow::{bail, Context, Result};
use std::path::Path;
use tracing::{info, warn};
use walkdir::DirEntry;

use crate::{
    api::releases::{Release, ReleaseBuilder},
    sourcemaps::{
        args::{FileSelectionArgs, ReleaseArgs, ReleaseMode},
        constant::CHUNK_ID_NAMESPACE,
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

    /// How the release is associated with exceptions. `symbol-set` (the default) stamps the
    /// release id into the sourcemap so the uploaded symbol set is bound to it: the previous
    /// behavior. EXPERIMENTAL `event` injects the release id into each chunk as
    /// `_posthogReleaseId` so the SDK emits it on every exception, and derives
    /// content-addressed chunk ids that are stable across rebuilds. Also settable via
    /// `POSTHOG_RELEASE_MODE`.
    #[arg(
        long,
        env = "POSTHOG_RELEASE_MODE",
        value_enum,
        default_value = "symbol-set"
    )]
    pub release_mode: ReleaseMode,
}

impl InjectArgs {
    pub fn validate(&self) -> Result<()> {
        self.file_selection.validate()
    }
}

/// Where an event-mode build's release comes from at runtime.
///
/// Web and Node bundles carry it in the chunk. The injected snippet sets `_posthogReleaseId`,
/// and the SDK emits it on every exception. React Native cannot do this. The injected JS
/// compiles to Hermes bytecode, and no SDK reads the global out of it. There the server
/// rebuilds the release from the `$app_namespace` / `$app_version` / `$app_build` that every
/// event already carries. This is what it does for iOS dSYMs and Android mappings.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventReleaseSource {
    EmbeddedInChunk,
    AppMetadata,
}

pub fn inject_impl(
    args: &InjectArgs,
    matcher: impl Fn(&DirEntry) -> bool + 'static,
    existing_release: Option<&Release>,
    event_release_source: EventReleaseSource,
) -> Result<()> {
    let InjectArgs {
        file_selection,
        public_path_prefix,
        release,
        release_mode,
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

    match release_mode {
        ReleaseMode::Event => {
            // The release id travels inside each chunk for the SDK to emit, rather than being
            // stamped into the sourcemap, so the release exists but nothing binds a symbol set
            // to it. When the SDK reads the release from the app instead, only the chunk ids go
            // in. The upload then creates the release row that the server resolves onto.
            let release_id = match event_release_source {
                EventReleaseSource::EmbeddedInChunk => {
                    let release_id = resolve_release_id(release.clone(), existing_release)?;
                    if release_id.is_none() {
                        warn!(
                            "no release could be resolved, injecting chunk ids only — events will carry no release"
                        );
                    }
                    release_id
                }
                EventReleaseSource::AppMetadata => None,
            };
            pairs = inject_pairs(pairs, release_id.as_deref())?;
        }
        ReleaseMode::SymbolSet => {
            // Fetch or create a release over the API and stamp its id into the sourcemap,
            // binding the uploaded symbol set to it.
            let created_release_id = if let Some(r) = existing_release {
                Some(r.id.to_string())
            } else {
                let cwd = std::env::current_dir()?;
                get_release_for_maps(&cwd, release.clone(), pairs.iter().map(|p| &p.sourcemap))?
                    .as_ref()
                    .map(|r| r.id.to_string())
            };
            pairs = inject_pairs_legacy(pairs, created_release_id)?;
        }
    }

    // Write the source and sourcemaps back to disk
    for pair in &pairs {
        pair.save()?;
    }
    info!("injecting done");
    Ok(())
}

/// Event-mode injection (`--release-mode=event`): content-addressed chunk ids plus an optional
/// `_posthogReleaseId` payload. A bundler-emitted debug id, when present, is adopted as the
/// chunk id so one id identifies the chunk across the whole toolchain.
pub fn inject_pairs(
    mut pairs: Vec<SourcePair>,
    release_id: Option<&str>,
) -> Result<Vec<SourcePair>> {
    for pair in &mut pairs {
        let Some(chunk_id) = pair.get_chunk_id() else {
            let chunk_id = adopted_debug_id(pair)
                .unwrap_or_else(|| stable_chunk_id(&pair.source.inner.content));
            pair.add_chunk_id(chunk_id, release_id)?;
            continue;
        };

        // Already injected: the chunk id is content-addressed and the content didn't change,
        // so keep it — but refresh the embedded release id when a different release resolved,
        // or a re-run over an existing dist would keep reporting the old release on every
        // event. When no release resolves, leave the pair untouched: failing to resolve is
        // missing information (e.g. no git context), not evidence the embedded id is stale.
        let Some(release_id) = release_id else {
            continue;
        };
        if pair.get_injected_release_id().as_deref() == Some(release_id) {
            continue;
        }
        pair.remove_chunk_id(chunk_id.clone())?;
        pair.add_chunk_id(chunk_id, Some(release_id))?;
    }

    Ok(pairs)
}

/// A bundler-emitted ECMA-426 debug id is already content-derived, so adopt it as the chunk id
/// instead of deriving our own. Non-UUID values are refused: the id flows into upload rows and
/// SDK events, and a malformed one is worse than a derived one.
fn adopted_debug_id(pair: &SourcePair) -> Option<String> {
    let debug_id = pair.get_debug_id()?;
    if uuid::Uuid::parse_str(&debug_id).is_err() {
        warn!(
            "ignoring malformed debug id {:?} on {} — falling back to a content-derived chunk id",
            debug_id,
            pair.source.inner.path.display()
        );
        return None;
    }
    Some(debug_id)
}

/// Symbol-set-mode injection (the default): a random per-build chunk id and the created release
/// id stamped into the sourcemap. Regenerates the chunk id whenever the release id changes or is
/// missing.
pub fn inject_pairs_legacy(
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
                pair.add_chunk_id(chunk_id, None)?;
            }
        }
    }

    Ok(pairs)
}

/// Deterministically derive a chunk id from the pristine minified source (UUIDv5). Identical
/// builds produce identical ids on every machine and rebuild, so uploads dedupe instead of
/// minting a per-build random id.
///
/// The sourcemap is deliberately not part of the identity. It carries `sourcesContent`, so a
/// comment-only edit rewrites the map while the minified code stays byte-identical, and folding
/// the map in would mint a new chunk for code that never changed. The map still reaches the
/// server, because the upload hashes the payload it sends: a map-only change is a content
/// change, and event mode overwrites the stored symbol set with the newer map.
fn stable_chunk_id(source_content: &str) -> String {
    uuid::Uuid::new_v5(&CHUNK_ID_NAMESPACE, source_content.as_bytes()).to_string()
}

/// Resolve the release row whose id gets injected into the chunks. Reuses the release already
/// fetched upstream (the `process` command) when there is one; otherwise resolves name/version
/// from flags and git/CI metadata and fetches or creates the row. Returns `None` only when there
/// isn't enough information to identify a release at all.
fn resolve_release_id(
    release: ReleaseArgs,
    existing_release: Option<&Release>,
) -> Result<Option<String>> {
    if let Some(r) = existing_release {
        return Ok(Some(r.id.to_string()));
    }
    Ok(resolve_release(release)?.map(|r| r.id.to_string()))
}

/// Fetch or create the release identified by `release`, filling in whichever of name and version
/// the flags left out from git and CI metadata. Returns `None` when neither source identifies a
/// release.
///
/// Shared with the `release resolve` command, so a build tool that injects the release id itself
/// lands on the same row `sourcemap inject --release-mode=event` would have injected.
pub fn resolve_release(release: ReleaseArgs) -> Result<Option<Release>> {
    let cwd = std::env::current_dir()?;
    let release = release.resolve_info_plist()?;
    let mut builder: ReleaseBuilder = release.into();
    add_git_info_to_release_builder(&cwd, &mut builder)?;
    if !builder.can_create() {
        return Ok(None);
    }
    Ok(Some(builder.fetch_or_create()?))
}

pub fn get_release_for_maps<'a>(
    directory: &Path,
    release: ReleaseArgs,
    maps: impl IntoIterator<Item = &'a SourceMapFile>,
) -> Result<Option<Release>> {
    // We need to fetch or create a release if: the user specified one, any pair is missing one, or the user
    // forced release overriding
    let release = release.resolve_info_plist()?;
    let needs_release = release.name.is_some()
        || release.version.is_some()
        || release.build.is_some()
        || maps.into_iter().any(|p| !p.has_release_id());

    let mut created_release = None;
    if needs_release {
        let mut builder: ReleaseBuilder = release.into();

        add_git_info_to_release_builder(directory, &mut builder)?;

        if builder.can_create() {
            created_release = Some(builder.fetch_or_create()?);
        }
    }

    Ok(created_release)
}

fn add_git_info_to_release_builder(directory: &Path, builder: &mut ReleaseBuilder) -> Result<()> {
    let needs_git_for_release_fields = !builder.can_create();
    let release_fields_were_provided = builder.has_name() || builder.has_version();

    match get_git_info(Some(directory.to_path_buf())) {
        Ok(Some(info)) => {
            builder.with_git(info);
        }
        Ok(None) if needs_git_for_release_fields && release_fields_were_provided => {
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
    use crate::sourcemaps::plain::inject::is_javascript_file;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    const XCODE_RELEASE_ENV_VARS: &[&str] = &[
        "PRODUCT_BUNDLE_IDENTIFIER",
        "MARKETING_VERSION",
        "CURRENT_PROJECT_VERSION",
    ];

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
            info_plist: None,
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

    fn chunk_id_for(sourcemap: &str) -> String {
        let dir = tempfile::tempdir().expect("failed to create temporary directory");
        fs::write(
            dir.path().join("app.js"),
            "console.log(1);\n//# sourceMappingURL=app.js.map\n",
        )
        .expect("failed to write source");
        fs::write(dir.path().join("app.js.map"), sourcemap).expect("failed to write sourcemap");

        let selection = FileSelection::from_roots(vec![dir.path().to_path_buf()])
            .include(vec![])
            .expect("failed to build selection")
            .exclude(vec![])
            .expect("failed to build selection");
        let pairs = read_pairs(selection.into_iter().filter(is_javascript_file), &None);

        inject_pairs(pairs, None)
            .expect("failed to inject pairs")
            .first()
            .and_then(SourcePair::get_chunk_id)
            .expect("injected pair carries a chunk id")
    }

    #[test]
    fn map_only_changes_keep_the_chunk_id() {
        // Bundlers embed the original file in `sourcesContent`, so editing a comment rewrites
        // the map while the minified code stays byte-identical. Folding the map into the id
        // would mint a new chunk on every such edit and orphan the symbol set already stored.
        let one = chunk_id_for(
            r#"{"version":3,"sources":["app.ts"],"sourcesContent":["// one\nconsole.log(1)\n"],"mappings":"AAAA","names":[]}"#,
        );
        let two = chunk_id_for(
            r#"{"version":3,"sources":["app.ts"],"sourcesContent":["// two\nconsole.log(1)\n"],"mappings":"AAAA","names":[]}"#,
        );

        assert_eq!(one, two);
    }

    #[test]
    fn stable_chunk_id_tracks_the_minified_source() {
        let id = stable_chunk_id("code();");

        assert_eq!(id, stable_chunk_id("code();"));
        assert_ne!(id, stable_chunk_id("other();"));
    }

    #[test]
    fn git_failure_is_not_fatal_when_release_fields_are_explicit() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = make_git_repo_without_branch_ref();
        let mut builder: ReleaseBuilder = release_args(Some("my-app"), Some("1.0.0")).into();

        let result = add_git_info_to_release_builder(temp_root.path(), &mut builder);

        assert!(result.is_ok());
        assert!(builder.can_create());
    }

    #[test]
    fn git_failure_is_fatal_when_release_fields_need_git() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = make_git_repo_without_branch_ref();
        let mut builder: ReleaseBuilder = release_args(Some("my-app"), None).into();

        let error = add_git_info_to_release_builder(temp_root.path(), &mut builder)
            .expect_err("git failure should remain fatal when release fields are incomplete");

        assert!(format!("{error:#}").contains("Failed to determine git info for release"));
    }

    #[test]
    fn missing_git_is_not_fatal_for_best_effort_release_creation() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = tempfile::tempdir().expect("failed to create temporary directory");
        let mut builder: ReleaseBuilder = release_args(None, None).into();

        let result = add_git_info_to_release_builder(temp_root.path(), &mut builder);

        assert!(result.is_ok());
        assert!(!builder.can_create());
    }

    #[test]
    fn unresolved_info_plist_is_not_fatal_without_git_or_xcode_environment() {
        let _env_lock = lock_env();
        let _git_env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let _xcode_env_guard = EnvVarGuard::clear(XCODE_RELEASE_ENV_VARS);
        let temp_root = tempfile::tempdir().expect("failed to create temporary directory");
        let info_plist = temp_root.path().join("Info.plist");
        fs::write(
            &info_plist,
            r#"<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
    <key>CFBundleShortVersionString</key>
    <string>$(MARKETING_VERSION)</string>
    <key>CFBundleVersion</key>
    <string>$(CURRENT_PROJECT_VERSION)</string>
</dict>
</plist>"#,
        )
        .expect("failed to write Info.plist");
        let mut args = release_args(None, None);
        args.info_plist = Some(info_plist);
        let resolved = args
            .resolve_info_plist()
            .expect("Info.plist should be readable");
        let mut builder: ReleaseBuilder = resolved.into();

        let result = add_git_info_to_release_builder(temp_root.path(), &mut builder);

        assert!(result.is_ok());
        assert!(!builder.can_create());
    }

    #[test]
    fn missing_git_is_fatal_when_release_args_are_incomplete() {
        let _env_lock = lock_env();
        let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);
        let temp_root = tempfile::tempdir().expect("failed to create temporary directory");
        let mut builder: ReleaseBuilder = release_args(Some("my-app"), None).into();

        let error = add_git_info_to_release_builder(temp_root.path(), &mut builder)
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
