use std::path::PathBuf;

use anyhow::{anyhow, Result};
use tracing::info;

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

    /// How the release is associated with exceptions. `symbol-set` is the default. It stamps the
    /// release id into the source maps, so the upload binds the symbol set to that release.
    /// EXPERIMENTAL `event` stamps nothing and leaves the maps release-independent. Each event
    /// then resolves its own release from the app version and namespace the SDK already sends.
    /// The coordinates you pass to `hermes upload` must match the app's. Also settable via
    /// `POSTHOG_RELEASE_MODE`.
    #[arg(
        long,
        env = "POSTHOG_RELEASE_MODE",
        value_enum,
        default_value = "symbol-set"
    )]
    pub release_mode: ReleaseMode,
}

pub fn clone(args: &CloneArgs) -> Result<()> {
    context().capture_command_invoked("hermes_clone");

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
        ReleaseMode::SymbolSet => {
            get_release_for_maps(minified_map_path, release.clone(), [&minified_map])?
                .map(|r| r.id.to_string())
        }
    };

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

/// Carry the chunk identity and release from the packager map into the hermes-composed map.
/// Expo stamps only a `debugId` on the packager map, so the id must come from the upload
/// fallback — reading the stamped chunk id alone leaves the composed map id-less and the
/// upload silently empty.
pub fn clone_metadata(minified_map: &SourceMapFile, composed_map: &mut SourceMapFile) {
    if let Some(chunk_id) = minified_map.get_upload_chunk_id() {
        composed_map.set_chunk_id(Some(chunk_id));
    }

    // Copy the id even when there is none. A build that changes to event release mode then
    // clears the id a previous run stamped. Without this, the composed map uploads still bound
    // to that release.
    composed_map.set_release_id(minified_map.get_release_id());
}

#[cfg(test)]
mod test {
    use super::clone_metadata;
    use crate::sourcemaps::content::SourceMapFile;
    use crate::utils::files::SourceFile;
    use std::path::PathBuf;

    fn map_from(json: serde_json::Value) -> SourceMapFile {
        SourceMapFile {
            inner: SourceFile::new(
                PathBuf::from("main.jsbundle.map"),
                serde_json::from_value(json).unwrap(),
            ),
        }
    }

    #[test]
    fn clone_carries_a_debug_id_only_packager_map_into_the_composed_map() {
        // The Expo metro plugin stamps only `debugId` on the packager map. Clone must land
        // that id on the composed map, or `hermes upload` finds no id and uploads nothing
        // while the build stays green.
        let minified = map_from(serde_json::json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["App.js"],
            "names": [],
            "debugId": "c96bfa94-ca84-4f98-8d5e-f15adba692ca",
            "release_id": "11111111-2222-4333-8444-555555555555",
        }));
        let mut composed = map_from(serde_json::json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["App.js"],
            "names": [],
            "x_hermes_function_offsets": {},
        }));

        clone_metadata(&minified, &mut composed);

        assert_eq!(
            composed.get_chunk_id().as_deref(),
            Some("c96bfa94-ca84-4f98-8d5e-f15adba692ca")
        );
        assert_eq!(
            composed.get_release_id().as_deref(),
            Some("11111111-2222-4333-8444-555555555555")
        );
    }

    #[test]
    fn clone_clears_a_release_id_the_composed_map_still_carries() {
        // A build that changes to event release mode still has the previous run's release id on
        // the composed map. To copy only the ids that exist would upload it bound to that
        // release. That is the collision event mode prevents.
        let minified = map_from(serde_json::json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["App.js"],
            "names": [],
            "debugId": "c96bfa94-ca84-4f98-8d5e-f15adba692ca",
        }));
        let mut composed = map_from(serde_json::json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["App.js"],
            "names": [],
            "release_id": "11111111-2222-4333-8444-555555555555",
            "x_hermes_function_offsets": {},
        }));

        clone_metadata(&minified, &mut composed);

        assert_eq!(composed.get_release_id(), None);
    }
}
