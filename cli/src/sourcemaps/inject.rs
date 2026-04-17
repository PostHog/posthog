use anyhow::{bail, Result};
use std::path::Path;
use tracing::{info, warn};
use walkdir::DirEntry;

use crate::{
    api::releases::{is_hash_already_in_use, Release, ReleaseBuilder},
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

pub fn inject_impl(args: &InjectArgs, matcher: impl Fn(&DirEntry) -> bool + 'static) -> Result<()> {
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

    let cwd = std::env::current_dir()?;

    // If a concurrent CLI invocation has already created the release, the `by_hash` GET used
    // inside `get_release_for_maps` can briefly serve a stale 404 — the follow-up POST then
    // fails with `Hash id ... already in use`. Treat that as a signal to proceed without a
    // release association (chunk_ids still get injected) rather than aborting the run.
    let created_release_id = match get_release_for_maps(
        &cwd,
        release.clone(),
        pairs.iter().map(|p| &p.sourcemap),
    ) {
        Ok(release) => release.as_ref().map(|r| r.id.to_string()),
        Err(err) if is_hash_already_in_use(&err) => {
            warn!(
                    "release already exists (created concurrently); injecting chunk ids without a release association: {}",
                    err
                );
            None
        }
        Err(err) => return Err(err),
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
        || maps.into_iter().any(|p| !p.has_release_id());

    let mut created_release = None;
    if needs_release {
        let mut builder: ReleaseBuilder = release.into();

        get_git_info(Some(directory.to_path_buf()))?.map(|info| builder.with_git(info));

        if builder.can_create() {
            created_release = Some(builder.fetch_or_create()?);
        }
    }

    Ok(created_release)
}
