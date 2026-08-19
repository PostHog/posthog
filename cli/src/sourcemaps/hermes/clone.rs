use std::path::PathBuf;

use anyhow::{anyhow, Result};
use tracing::info;

use crate::{
    invocation_context::context,
    sourcemaps::{args::ReleaseArgs, content::SourceMapFile, inject::get_release_for_maps},
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
}

pub fn clone(args: &CloneArgs) -> Result<()> {
    context().capture_command_invoked("hermes_clone");

    let CloneArgs {
        minified_map_path,
        composed_map_path,
        release,
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

    let release_id = get_release_for_maps(minified_map_path, release.clone(), [&minified_map])?
        .map(|r| r.id.to_string());

    // The flow here differs from plain sourcemap injection a bit - here, we don't ever
    // overwrite the chunk ID, because at this point in the build process, we no longer
    // control what chunk ID is inside the compiled hermes byte code bundle. So, instead,
    // we permit e.g. uploading the same chunk ID's to two different posthog envs with two
    // different release ID's, or arbitrarily re-running the upload command, but if someone
    // tries to run `clone` twice, changing release but not posthog env, we'll error out. The
    // correct way to upload the same set of artefacts to the same posthog env as part of
    // two different releases is, 1, not to, but failing that, 2, to re-run the bundling process
    if !minified_map.has_release_id() || minified_map.get_release_id() != release_id {
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

    if let Some(release_id) = minified_map.get_release_id() {
        composed_map.set_release_id(Some(release_id));
    }
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
}
