// Copied from posthog-cli's `sourcemaps/hermes/clone.rs` and `upload.rs`, so the maps written and
// the containers uploaded are the bytes posthog-cli produces.

use anyhow::Result;
use posthog_symbol_data::{write_symbol_data, HermesMap};
use serde::Serialize;
use std::{
    fs,
    path::{Path, PathBuf},
};

use crate::{
    node,
    pair::SourceMapContent,
    upload::{content_hash, write_container},
};

const CONTAINER_PREFIX: &str = "map";
const CONTAINER_EXTENSION: &str = "symbolset";

pub struct MapFile {
    pub path: PathBuf,
    pub content: SourceMapContent,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Built {
    content_hash: String,
    size: usize,
    path: Option<String>,
}

pub fn load(path: &Path) -> Result<MapFile, String> {
    let text = node::read_text(path)?;
    let content = serde_json::from_str(&text).map_err(|error| error.to_string())?;

    Ok(MapFile {
        path: path.to_path_buf(),
        content,
    })
}

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
    pub fn write(&self) -> Result<(), String> {
        let bytes = self
            .content
            .serialize()
            .map_err(|error| error.to_string())?;

        fs::write(&self.path, bytes).map_err(|error| node::message(&error, "open", &self.path))
    }
}

pub fn build(id: usize, map: MapFile, folder: Option<&Path>) -> Result<Built> {
    let container = write_symbol_data(HermesMap {
        sourcemap: String::from_utf8(map.content.serialize()?)?,
    })?;

    let path = match folder {
        Some(folder) => {
            let path = folder.join(format!("{CONTAINER_PREFIX}-{id}.{CONTAINER_EXTENSION}"));
            write_container(&path, &container)?;
            Some(path.to_string_lossy().into_owned())
        }
        None => None,
    };

    Ok(Built {
        content_hash: content_hash([&container]),
        size: container.len(),
        path,
    })
}
