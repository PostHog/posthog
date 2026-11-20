// Mirrors cli/src/sourcemaps/hermes/clone.rs and upload.rs; keep byte output identical.

use anyhow::Result;
use posthog_symbol_data::{write_symbol_data, HermesMap};
use std::path::{Path, PathBuf};

use crate::{
    node,
    pair::SourceMapContent,
    upload::{Container, Prepared},
    write,
};

const SKIPPED_NO_CHUNK_ID: &str =
    "the map has no chunk ID. Run `hog error-tracking clone` after the Hermes build.";
const SKIPPED_EMPTY: &str = "the sourcemap is empty. Check your bundler sourcemap setting.";

pub struct MapFile {
    pub path: PathBuf,
    pub content: SourceMapContent,
}

pub fn load(path: &Path) -> Result<MapFile, String> {
    let text = node::read_text(path)?;
    let content = serde_json::from_str(&text).map_err(|error| error.to_string())?;

    Ok(MapFile {
        path: path.to_path_buf(),
        content,
    })
}

// Expo stamps only a `debugId` on the packager map, so a map uploads under it when it has no chunk
// id.
pub fn upload_chunk_id(content: &SourceMapContent) -> Option<String> {
    content
        .chunk_id
        .clone()
        .or_else(|| content.debug_id.clone())
}

// The chunk id inside the compiled bytecode can't change after the Hermes build, so the composed
// map takes the packager map's id and never mints one. The release is copied even when there is
// none: a build that changes to event mode then clears the id an earlier run stamped.
pub fn clone_metadata(from: &SourceMapContent, to: &mut SourceMapContent) {
    if let Some(chunk_id) = upload_chunk_id(from) {
        to.chunk_id = Some(chunk_id);
    }

    to.release_id = from.release_id.clone();
}

impl MapFile {
    pub fn stage(&self) -> Result<write::Staged, String> {
        let bytes = self
            .content
            .serialize()
            .map_err(|error| error.to_string())?;

        write::stage(&self.path, &bytes)
    }
}

pub fn upload_id(map: &MapFile) -> Result<String, &'static str> {
    let chunk_id = upload_chunk_id(&map.content).ok_or(SKIPPED_NO_CHUNK_ID)?;
    if map.content.is_empty() {
        return Err(SKIPPED_EMPTY);
    }
    Ok(chunk_id)
}

pub fn prepare(
    id: usize,
    chunk_id: String,
    map: MapFile,
    folder: Option<&Path>,
) -> Result<Prepared> {
    let release_id = map.content.release_id.clone();
    let bytes = write_symbol_data(HermesMap {
        sourcemap: String::from_utf8(map.content.serialize()?)?,
    })?;

    Ok(Prepared {
        id,
        chunk_id,
        release_id,
        container: Container::write(&bytes, folder)?,
    })
}
