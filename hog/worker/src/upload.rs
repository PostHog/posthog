// The symbol set a pair uploads as. Copied from posthog-cli's `sourcemaps/source_pairs.rs` and
// `plain/upload.rs`, and built with the posthog-symbol-data crate posthog-cli uses, so the
// container and its content hash are the ones PostHog already stores for a posthog-cli upload.

use anyhow::{anyhow, Result};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha512};
use std::{borrow::Cow, fs, path::Path};

use crate::{node, pair::SourcePair, ReleaseMode};

// Keep in step with WRAPPER_JS_SIZE_THRESHOLD_BYTES in cli/src/sourcemaps/plain/upload.rs. A
// smaller bundle with an empty map is a wrapper the bundler wrote, with nothing to symbolicate.
const WRAPPER_JS_SIZE_THRESHOLD_BYTES: usize = 4096;
// The control characters keep the token from matching anything a bundler writes.
const FILE_PATH_TOKEN: &str = "\u{1}file-path\u{1}";
const CONTAINER_EXTENSION: &str = "symbolset";

const SKIPPED_NO_ID: &str =
    "no PostHog chunk ID or native debug ID. Run `hog error-tracking inject` first.";
const SKIPPED_EMPTY_WRAPPER: &str = "the sourcemap is empty";
const SKIPPED_EMPTY_SUSPECT: &str =
    "the sourcemap is empty although the file is large. Check your bundler sourcemap setting.";

// SHA-512 over the parts joined with nothing in between, as lowercase hex.
pub fn content_hash<Item: AsRef<[u8]>>(parts: impl IntoIterator<Item = Item>) -> String {
    let mut hasher = Sha512::new();
    for part in parts {
        hasher.update(part.as_ref());
    }
    format!("{:x}", hasher.finalize())
}

#[derive(Serialize)]
#[serde(untagged)]
pub enum Prepared {
    Skipped {
        skipped: &'static str,
    },
    #[serde(rename_all = "camelCase")]
    Container {
        chunk_id: String,
        release_id: Option<String>,
        content_hash: String,
        size: usize,
        // Null in a dry run, which writes nothing.
        path: Option<String>,
    },
}

// Replaces every script file path in `text` with one token, for the event-mode content hash.
// With content-hashed file names every release renames every chunk, because each chunk carries
// the release id, and the names appear inside chunks: imports, `sourceMappingURL` and the map's
// `file`. A path is a run of path characters that ends in `.js`, `.mjs` or `.cjs` with no
// identifier character after it.
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

// Builds the container of one pair and writes it to `<folder>/<id>.symbolset`. The payload is
// always the injected pair. In symbol-set mode the hash covers the container itself.
pub fn prepare(
    id: usize,
    pair: SourcePair,
    mode: ReleaseMode,
    folder: Option<&Path>,
) -> Result<Prepared> {
    let injected_chunk_id = pair.chunk_id();
    let Some(chunk_id) = injected_chunk_id.clone().or_else(|| pair.debug_id()) else {
        return Ok(Prepared::Skipped {
            skipped: SKIPPED_NO_ID,
        });
    };
    if pair.map.is_empty() {
        let skipped = if pair.source.len() < WRAPPER_JS_SIZE_THRESHOLD_BYTES {
            SKIPPED_EMPTY_WRAPPER
        } else {
            SKIPPED_EMPTY_SUSPECT
        };
        return Ok(Prepared::Skipped { skipped });
    }

    let release_id = pair.map.release_id.clone();
    let container = write_symbol_data(SourceAndMap {
        minified_source: pair.source.clone(),
        sourcemap: String::from_utf8(pair.map.serialize()?)?,
    })?;
    let content_hash = match mode {
        ReleaseMode::Event => event_mode_hash(pair, injected_chunk_id.as_deref())?,
        ReleaseMode::SymbolSet => content_hash([&container]),
    };

    let path = match folder {
        Some(folder) => {
            let path = folder.join(format!("{id}.{CONTAINER_EXTENSION}"));
            write_container(&path, &container)?;
            Some(path.to_string_lossy().into_owned())
        }
        None => None,
    };

    Ok(Prepared::Container {
        chunk_id,
        release_id,
        content_hash,
        size: container.len(),
        path,
    })
}

pub fn write_container(path: &Path, container: &[u8]) -> Result<()> {
    fs::write(path, container).map_err(|error| anyhow!(node::message(&error, "open", path)))
}
