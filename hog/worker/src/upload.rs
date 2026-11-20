// Mirrors cli/src/sourcemaps/source_pairs.rs and plain/upload.rs; keep byte output identical.

use anyhow::{anyhow, Result};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha512};
use std::{
    borrow::Cow,
    collections::HashSet,
    fs,
    path::Path,
    sync::atomic::{AtomicUsize, Ordering},
};

use crate::{node, pair::SourcePair, ReleaseMode};

// A smaller bundle with an empty map is a wrapper the bundler wrote, with nothing to symbolicate.
const WRAPPER_JS_SIZE_THRESHOLD_BYTES: usize = 4096;
// The control characters keep the token from matching anything a bundler writes.
const FILE_PATH_TOKEN: &str = "\u{1}file-path\u{1}";
const CONTAINER_EXTENSION: &str = "symbolset";

const SKIPPED_NO_ID: &str =
    "no PostHog chunk ID or native debug ID. Run `hog error-tracking inject` first.";
const SKIPPED_EMPTY_WRAPPER: &str = "the sourcemap is empty";
const SKIPPED_EMPTY_SUSPECT: &str =
    "the sourcemap is empty although the file is large. Check your bundler sourcemap setting.";

pub fn content_hash<Item: AsRef<[u8]>>(parts: impl IntoIterator<Item = Item>) -> String {
    let mut hasher = Sha512::new();
    for part in parts {
        hasher.update(part.as_ref());
    }
    format!("{:x}", hasher.finalize())
}

// Every kind of symbol set writes to one folder, so the files are numbered across the worker's life.
static NEXT_CONTAINER_FILE: AtomicUsize = AtomicUsize::new(0);

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Container {
    pub content_hash: String,
    pub size: usize,
    // Null in a dry run, which writes nothing.
    pub path: Option<String>,
}

impl Container {
    pub fn write(bytes: &[u8], folder: Option<&Path>) -> Result<Self> {
        Self::write_with_hash(bytes, folder, content_hash([bytes]))
    }

    pub fn write_with_hash(
        bytes: &[u8],
        folder: Option<&Path>,
        content_hash: String,
    ) -> Result<Self> {
        let path = match folder {
            Some(folder) => {
                let number = NEXT_CONTAINER_FILE.fetch_add(1, Ordering::Relaxed);
                let path = folder.join(format!("{number}.{CONTAINER_EXTENSION}"));
                fs::write(&path, bytes)
                    .map_err(|error| anyhow!(node::message(&error, "open", &path)))?;
                Some(path.to_string_lossy().into_owned())
            }
            None => None,
        };

        Ok(Container {
            content_hash,
            size: bytes.len(),
            path,
        })
    }
}

#[derive(Serialize)]
pub struct SkippedPair {
    id: usize,
    reason: &'static str,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreparedPair {
    id: usize,
    chunk_id: String,
    release_id: Option<String>,
    #[serde(flatten)]
    container: Container,
}

pub struct Prepared {
    pub skipped: Vec<SkippedPair>,
    pub ready: Vec<(usize, String, SourcePair)>,
    pub duplicates: Vec<String>,
}

// Replaces every script file path with one token for the event-mode content hash, because with
// content-hashed file names every release renames every chunk, and the names appear inside
// chunks: imports, `sourceMappingURL` and the map's `file`.
fn without_file_paths(text: &str) -> Cow<'_, str> {
    let bytes = text.as_bytes();
    let mut normalized = String::new();
    let mut copied = 0;
    let mut searched = 0;
    while let Some(found) = text[searched..].find("js") {
        let js = searched + found;
        let end = js + 2;
        searched = end;
        let extension = if js >= 1 && bytes[js - 1] == b'.' {
            js - 1
        } else if js >= 2 && matches!(bytes[js - 1], b'm' | b'c') && bytes[js - 2] == b'.' {
            js - 2
        } else {
            continue;
        };
        if text[end..].chars().next().is_some_and(is_identifier_char) {
            continue;
        }
        // Walking back stops at what was already replaced, which keeps the scan linear.
        let Some(start) = text[copied..extension]
            .char_indices()
            .rev()
            .take_while(|(_, c)| is_path_char(*c))
            .last()
            .map(|(offset, _)| copied + offset)
        else {
            continue;
        };
        if normalized.is_empty() {
            normalized.reserve(text.len());
        }
        normalized.push_str(&text[copied..start]);
        normalized.push_str(FILE_PATH_TOKEN);
        copied = end;
    }
    if normalized.is_empty() {
        return Cow::Borrowed(text);
    }
    normalized.push_str(&text[copied..]);
    Cow::Owned(normalized)
}

fn is_identifier_char(c: char) -> bool {
    c.is_alphanumeric() || matches!(c, '_' | '$')
}

fn is_path_char(c: char) -> bool {
    is_identifier_char(c) || matches!(c, '-' | '.' | '/' | '\\' | '~' | '@' | '+')
}

// The hash of the pair with the injection undone and script paths replaced, so it stays the same
// across releases and rebuilds. It still covers which snippet the bundle carries: the release
// snippet is longer, so the two variants of one chunk upload different maps.
fn event_mode_hash(mut pair: SourcePair, injected_chunk_id: Option<&str>) -> Result<String> {
    let variant: &[u8] = match injected_chunk_id {
        Some(chunk_id) => {
            // Read before the removal, which erases the evidence.
            let variant: &[u8] = if pair.has_release_snippet(chunk_id) {
                b"with-release"
            } else {
                b"chunk-id-only"
            };
            pair.remove_chunk_id(chunk_id)?;
            variant
        }
        None => b"native-debug-id",
    };

    if let Some(Value::String(file)) = pair.map.fields.get_mut("file") {
        if let Cow::Owned(normalized) = without_file_paths(file) {
            *file = normalized;
        }
    }
    let pristine_map = pair.map.serialize()?;
    let pristine_source = without_file_paths(&pair.source);

    // Serialized JSON never holds a raw NUL, so it separates the parts without ambiguity.
    Ok(content_hash([
        pristine_source.as_bytes(),
        b"\0".as_slice(),
        pristine_map.as_slice(),
        b"\0".as_slice(),
        variant,
    ]))
}

// A bundle with a native debug id and no chunk id carries the id its map is known by, so it goes
// first and wins over a later pair with the same id. A skipped pair claims no id.
pub fn claim(ids: &[usize], pairs: Vec<SourcePair>) -> Prepared {
    let mut skipped = Vec::new();
    let mut ready = Vec::new();
    for (id, pair) in ids.iter().zip(pairs) {
        match upload_id(&pair) {
            Ok(chunk_id) => ready.push((*id, chunk_id, pair)),
            Err(reason) => skipped.push(SkippedPair { id: *id, reason }),
        }
    }

    ready.sort_by_key(|(_, _, pair)| {
        !(pair.chunk_id().is_none() && pair.source_debug_id().is_some())
    });
    let mut claimed = HashSet::new();
    let mut duplicates = Vec::new();
    ready.retain(|(_, chunk_id, _)| {
        let first = claimed.insert(chunk_id.clone());
        if !first {
            duplicates.push(chunk_id.clone());
        }
        first
    });

    Prepared {
        skipped,
        ready,
        duplicates,
    }
}

fn upload_id(pair: &SourcePair) -> Result<String, &'static str> {
    let chunk_id = pair
        .chunk_id()
        .or_else(|| pair.debug_id())
        .ok_or(SKIPPED_NO_ID)?;
    if !pair.map.is_empty() {
        return Ok(chunk_id);
    }

    Err(if pair.source.len() < WRAPPER_JS_SIZE_THRESHOLD_BYTES {
        SKIPPED_EMPTY_WRAPPER
    } else {
        SKIPPED_EMPTY_SUSPECT
    })
}

// The payload is always the injected pair. In symbol-set mode the hash covers the container. The
// event-mode hash rewrites the pair, so the container leaves memory first.
pub fn prepare(
    id: usize,
    chunk_id: String,
    pair: SourcePair,
    mode: ReleaseMode,
    folder: Option<&Path>,
) -> Result<PreparedPair> {
    let release_id = pair.map.release_id.clone();
    let sourcemap = String::from_utf8(pair.map.serialize()?)?;

    let container = match mode {
        ReleaseMode::SymbolSet => {
            let bytes = write_symbol_data(SourceAndMap {
                minified_source: pair.source,
                sourcemap,
            })?;
            Container::write(&bytes, folder)?
        }
        ReleaseMode::Event => {
            let bytes = write_symbol_data(SourceAndMap {
                minified_source: pair.source.clone(),
                sourcemap,
            })?;
            let written = Container::write_with_hash(&bytes, folder, String::new())?;
            drop(bytes);

            let injected_chunk_id = pair.chunk_id();
            Container {
                content_hash: event_mode_hash(pair, injected_chunk_id.as_deref())?,
                ..written
            }
        }
    };

    Ok(PreparedPair {
        id,
        chunk_id,
        release_id,
        container,
    })
}
