use std::path::PathBuf;

use anyhow::{anyhow, Result};
pub use posthog_symbol_processing::sourcemaps::hermes::clone_metadata;
use tracing::{info, warn};

use crate::{
    invocation_context::context,
    sourcemaps::{
        args::{ReleaseArgs, ReleaseMode},
        content::SourceMapFile,
        inject::get_release_for_maps,
    },
};

#[derive(clap::Args)]
pub struct CloneArgs {
    /// The path of the minified source map
    #[arg(short, long)]
    pub minified_map_path: PathBuf,

    /// The path of the composed source map
    #[arg(short, long)]
    pub composed_map_path: PathBuf,

    #[clap(flatten)]
    pub release: ReleaseArgs,

    /// How the release is associated with exceptions. `event` is the default. It stamps nothing
    /// and leaves the maps release-independent. Each event then resolves its own release from the
    /// app version and namespace the SDK already sends. The coordinates you pass to
    /// `hermes upload` must match the app's. `symbol-set` stamps the release id into the source
    /// maps instead, so the upload binds the symbol set to that release. Also settable via
    /// `POSTHOG_RELEASE_MODE`.
    #[arg(
        long,
        env = "POSTHOG_RELEASE_MODE",
        value_enum,
        default_value = "event"
    )]
    pub release_mode: ReleaseMode,
}

pub fn clone(args: &CloneArgs) -> Result<()> {
    context().capture_command_invoked("hermes_clone");
    clone_maps(args)
}

fn clone_maps(args: &CloneArgs) -> Result<()> {
    let CloneArgs {
        minified_map_path,
        composed_map_path,
        release,
        release_mode,
    } = args;

    let mut minified_map = SourceMapFile::load(minified_map_path).map_err(|e| {
        anyhow!(
            "Failed to load minified map at '{}': {}",
            minified_map_path.display(),
            e
        )
    })?;

    let mut composed_map = SourceMapFile::load(composed_map_path).map_err(|e| {
        anyhow!(
            "Failed to load composed map at '{}': {}",
            composed_map_path.display(),
            e
        )
    })?;

    // Event mode resolves no release here. `hermes upload` creates the release row that the
    // server resolves an event's app metadata onto. The maps must stay without a release id.
    // A map id comes from the map's own content, so one symbol set serves every release.
    // Without this, a later release collides with the release that uploaded the map first.
    let release_id = match release_mode {
        ReleaseMode::Event => None,
        // Without release flags, a map that already carries a release resolves none, and that
        // release stays. `hermes inject` stamped it, and the upload binds the symbol set to it.
        ReleaseMode::SymbolSet => {
            get_release_for_maps(minified_map_path, release.clone(), [&minified_map])?
                .map(|r| r.id.to_string())
                .or_else(|| minified_map.get_release_id())
        }
    };

    if *release_mode == ReleaseMode::SymbolSet && release_id.is_none() {
        warn!("No release could be resolved. Sourcemaps will upload without a release. Pass both --release-name and --release-version, or run from a git repository or supported CI environment.");
    }

    // The flow here differs from plain sourcemap injection a bit - here, we don't ever
    // overwrite the chunk ID, because at this point in the build process, we no longer
    // control what chunk ID is inside the compiled hermes byte code bundle. So, instead,
    // we permit e.g. uploading the same chunk ID's to two different posthog envs with two
    // different release ID's, or arbitrarily re-running the upload command, but if someone
    // tries to run `clone` twice, changing release but not posthog env, we'll error out. The
    // correct way to upload the same set of artefacts to the same posthog env as part of
    // two different releases is, 1, not to, but failing that, 2, to re-run the bundling process
    if minified_map.get_release_id() != release_id {
        minified_map.set_release_id(release_id.clone());
        minified_map.save()?;
    }

    clone_metadata(&minified_map, &mut composed_map);

    composed_map.save()?;
    info!(
        "Successfully cloned metadata to {}",
        composed_map.inner.path.display()
    );

    info!("Finished cloning metadata");
    Ok(())
}

#[cfg(test)]
mod test {
    use super::{clone_maps, CloneArgs};
    use crate::sourcemaps::args::{ReleaseArgs, ReleaseMode};
    use crate::sourcemaps::content::SourceMapFile;

    #[test]
    fn symbol_set_clone_without_release_flags_keeps_the_stamped_release() {
        // `hermes inject` stamps the release into the packager map. A clone without release
        // flags resolves none, and must not clear it, or the upload binds to no release.
        let dir = tempfile::tempdir().unwrap();
        let minified_map_path = dir.path().join("main.jsbundle.map");
        let composed_map_path = dir.path().join("main.hbc.map");
        std::fs::write(
            &minified_map_path,
            serde_json::json!({
                "version": 3,
                "mappings": "AAAA",
                "sources": ["App.js"],
                "names": [],
                "chunk_id": "c96bfa94-ca84-4f98-8d5e-f15adba692ca",
                "release_id": "11111111-2222-4333-8444-555555555555",
            })
            .to_string(),
        )
        .unwrap();
        std::fs::write(
            &composed_map_path,
            serde_json::json!({
                "version": 3,
                "mappings": "AAAA",
                "sources": ["App.js"],
                "names": [],
                "x_hermes_function_offsets": {},
            })
            .to_string(),
        )
        .unwrap();

        clone_maps(&CloneArgs {
            minified_map_path: minified_map_path.clone(),
            composed_map_path: composed_map_path.clone(),
            release: ReleaseArgs {
                name: None,
                version: None,
                build: None,
                info_plist: None,
                skip_release_on_fail: true,
            },
            release_mode: ReleaseMode::SymbolSet,
        })
        .unwrap();

        for path in [minified_map_path, composed_map_path] {
            assert_eq!(
                SourceMapFile::load(&path)
                    .unwrap()
                    .get_release_id()
                    .as_deref(),
                Some("11111111-2222-4333-8444-555555555555")
            );
        }
    }
}
