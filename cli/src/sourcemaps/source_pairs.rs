use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::{
        args::ReleaseMode,
        content::{get_injected_release_id, MinifiedSourceFile, SourceMapContent, SourceMapFile},
    },
    utils::files::content_hash,
};
use anyhow::{anyhow, Context, Result};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use serde_json::Value;
use std::borrow::Cow;
use tracing::{debug, info, warn};
use walkdir::DirEntry;

#[derive(Debug)]
// Source pairs are the fundamental unit of a frontend symbol set
pub struct SourcePair {
    pub source: MinifiedSourceFile,
    pub sourcemap: SourceMapFile,
}

impl SourcePair {
    pub fn has_chunk_id(&self) -> bool {
        // Minified chunks are the source of truth for their ID's, not sourcemaps,
        // because sometimes sourcemaps are shared across multiple chunks.
        self.get_chunk_id().is_some()
    }

    pub fn get_chunk_id(&self) -> Option<String> {
        self.source.get_chunk_id()
    }

    /// Debug id already present in the pair, if any. The chunk's comment is authoritative
    /// (sourcemaps can be shared across chunks); the sourcemap's field is only a fallback.
    pub fn get_debug_id(&self) -> Option<String> {
        let source_debug_id = self.source.get_debug_id();
        let sourcemap_debug_id = self.sourcemap.get_debug_id();
        if let (Some(source_id), Some(map_id)) = (&source_debug_id, &sourcemap_debug_id) {
            if source_id != map_id {
                warn!(
                    "debug id mismatch for {}: chunk has {}, sourcemap has {} — using the chunk's",
                    self.source.inner.path.display(),
                    source_id,
                    map_id
                );
            }
        }
        source_debug_id.or(sourcemap_debug_id)
    }

    pub fn has_release_id(&self) -> bool {
        self.sourcemap.has_release_id()
    }

    pub fn get_release_id(&self) -> Option<String> {
        self.sourcemap.get_release_id()
    }

    /// The release id embedded in the source's injected snippet (event release mode),
    /// as opposed to `get_release_id`, which reads the one stamped into the sourcemap.
    pub fn get_injected_release_id(&self) -> Option<String> {
        let chunk_id = self.get_chunk_id()?;
        get_injected_release_id(&self.source.inner.content, &chunk_id)
    }

    pub fn remove_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        if self.get_chunk_id().as_ref() != Some(&chunk_id) {
            return Err(anyhow!("Chunk ID mismatch"));
        }
        let adjustment = self.source.remove_chunk_id(chunk_id)?;
        self.sourcemap.apply_adjustment(adjustment)?;
        self.sourcemap.set_chunk_id(None);
        Ok(())
    }

    pub fn update_chunk_id(
        &mut self,
        previous_chunk_id: String,
        new_chunk_id: String,
    ) -> Result<()> {
        self.remove_chunk_id(previous_chunk_id)?;
        self.add_chunk_id(new_chunk_id, None)?;
        Ok(())
    }

    pub fn add_chunk_id(&mut self, chunk_id: String, release_id: Option<&str>) -> Result<()> {
        if self.has_chunk_id() {
            return Err(anyhow!("Chunk ID already set"));
        }

        let adjustment = self.source.set_chunk_id(&chunk_id, release_id)?;
        // In cases where sourcemaps are shared across multiple chunks,
        // we should only apply the adjustment if the sourcemap doesn't
        // have a chunk ID set (since otherwise, it's already been adjusted)
        if self.sourcemap.get_chunk_id().is_none() {
            self.sourcemap.apply_adjustment(adjustment)?;
            self.sourcemap.set_chunk_id(Some(chunk_id));
        }
        Ok(())
    }

    pub fn set_release_id(&mut self, release_id: Option<String>) {
        self.sourcemap.set_release_id(release_id);
    }

    pub fn save(&self) -> Result<()> {
        self.source.save()?;
        self.sourcemap.save()?;
        Ok(())
    }
}

pub fn read_pairs(
    selection: impl Iterator<Item = DirEntry>,
    prefix: &Option<String>,
) -> Vec<SourcePair> {
    let mut seen_paths = std::collections::HashSet::new();
    let pairs = selection
        .filter_map(|entry| {
            let path = entry.path();
            let entry_path = path
                .canonicalize()
                .context("failed to canonicalize path")
                .map_err(|e| warn!("skip: {e:?}"))
                .ok()?;
            // Overlapping selection roots yield the same file more than once; a second
            // pass would stamp a fresh chunk id over the first and upload a stale copy.
            if !seen_paths.insert(entry_path.clone()) {
                return None;
            }
            let source = MinifiedSourceFile::load(&entry_path)
                .context("failed to read source")
                .map_err(|e| warn!("skip: {e:?}"))
                .ok()?;
            let sourcemap_path = source
                .get_sourcemap_path(prefix)
                .context("no sourcemap found")
                .map_err(|e| info!("skip: {e:?}"))
                .ok()
                .flatten()?;
            let sourcemap = SourceMapFile::load(&sourcemap_path)
                .context("failed to read sourcemap")
                .map_err(|e| warn!("skip: {e:?}"))
                .ok()?;
            debug!("adding pair for {}", entry_path.display());
            Some(SourcePair { source, sourcemap })
        })
        .collect::<Vec<SourcePair>>();
    info!("found {} pairs", pairs.len());
    pairs
}

/// Stands in for a script file path in the event-mode content hash. The control characters keep
/// it from colliding with anything a bundler writes.
const FILE_PATH_TOKEN: &str = "\u{1}file-path\u{1}";

/// Replace every script file path in `text` with the same token, for the event-mode content hash.
///
/// With content-hashed file names (Vite's default) a chunk is renamed whenever its bytes change,
/// and in event mode every chunk carries the release id, so every chunk is renamed on every
/// release. The names end up inside the chunks: the map's `file` field and the
/// `sourceMappingURL` comment hold the chunk's own name, and an import of another chunk holds
/// that chunk's name. Hashing them would upload every unchanged chunk again on every release
/// (PostHog/posthog#105956).
///
/// A path is a run of path characters ending in `.js`, `.mjs` or `.cjs`, where no identifier
/// character follows: `./index-C3e2Htc9.js` and the `index-C3e2Htc9.js` in
/// `index-C3e2Htc9.js.map`, but not `index.json` or `index.jsx`. The replacement depends on the
/// chunk alone, not on the other files in the upload, so two uploads of one chunk hash it alike,
/// and chunks that hashed alike before still do.
///
/// Leaving the paths out cannot keep a stored symbol set that resolves a frame to another file,
/// line or column. A frame resolves through the map's mappings, `sources`, `names` and
/// `sourcesContent`, and through scopes read from the minified source by position. The rest of the
/// map is hashed as it is, and a path whose length changes shifts the generated columns after it
/// on its line, which the mappings record. A run can also be code or a string key, such as
/// `e.options.js` or `{"one-BrAf3own.js"(){}}`, and a function can take its name from it. That name
/// could only go stale if one chunk id stood for two builds whose code differs inside a run, and
/// no chunk id does: `@posthog/rollup-plugin` derives its ids before the bundler turns imports into
/// file names, so its builds differ only in those names, and every other chunk id covers the final
/// content.
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
    is_identifier_char(c) || matches!(c, '-' | '.' | '/' | '~' | '@' | '+')
}

/// Replace the file path in the map's `file` field, the only field that names the chunk rather
/// than its sources.
fn without_file_path_in_file_field(map: &mut SourceMapContent) {
    if let Some(Value::String(file)) = map.fields.get_mut("file") {
        if let Cow::Owned(normalized) = without_file_paths(file) {
            *file = normalized;
        }
    }
}

impl SourcePair {
    /// Turn the pair into an upload payload. The payload always carries the injected artifact;
    /// only the content hash depends on the mode.
    ///
    /// In event mode the hash is computed over the pair with the injection undone (snippet and
    /// chunk-id comment removed, sourcemap adjustment reversed), because the embedded release id
    /// changes every release while the chunk id does not. The server keys its skip-or-conflict
    /// decision on this hash per chunk id, so hashing the embedded id would re-upload every chunk
    /// on every release.
    ///
    /// The hash does cover which snippet variant is embedded. The release variant is longer, so it
    /// shifts every generated column in the uploaded sourcemap. Two builds of one unchanged chunk,
    /// one before a release could be resolved and one after, therefore ship different maps. Equal
    /// hashes would make the server keep the first map and resolve later frames to the wrong
    /// source positions.
    ///
    /// The hash also leaves out script file paths, which change with every release when the
    /// bundler names chunks by content (see `without_file_paths`).
    ///
    /// In symbol-set mode no hash is set and the upload layer hashes the raw payload, matching
    /// the hashes the server already stores for previous uploads.
    pub fn into_upload(mut self, release_mode: ReleaseMode) -> Result<SymbolSetUpload> {
        let chunk_id = self.get_chunk_id().ok_or_else(|| {
            anyhow!(
                "Chunk ID not found in {}. Run 'sourcemap inject' before 'sourcemap upload', or use 'sourcemap process' to do both.",
                self.source.inner.path.display()
            )
        })?;
        let release_id = self.sourcemap.get_release_id();
        let source_content = self.source.inner.content.clone();
        let sourcemap_content = serde_json::to_string(&self.sourcemap.inner.content)?;

        let content_hash = match release_mode {
            ReleaseMode::Event => {
                // Read the variant before the removal, which erases the evidence.
                let snippet_variant: &[u8] = if self.source.has_release_snippet(&chunk_id) {
                    b"with-release"
                } else {
                    b"chunk-id-only"
                };
                self.remove_chunk_id(chunk_id.clone())?;
                without_file_path_in_file_field(&mut self.sourcemap.inner.content);
                let pristine_map = serde_json::to_string(&self.sourcemap.inner.content)?;
                let pristine_source = without_file_paths(&self.source.inner.content);
                // JSON serialization never contains a raw NUL, so it unambiguously separates
                // the parts (same framing as `stable_chunk_id`).
                Some(content_hash([
                    pristine_source.as_bytes(),
                    b"\0".as_slice(),
                    pristine_map.as_bytes(),
                    b"\0".as_slice(),
                    snippet_variant,
                ]))
            }
            ReleaseMode::SymbolSet => None,
        };

        let data = SourceAndMap {
            minified_source: source_content,
            sourcemap: sourcemap_content,
        };

        let data = write_symbol_data(data)?;

        Ok(SymbolSetUpload {
            chunk_id,
            data,
            release_id,
            content_hash,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn normalize(text: &str) -> String {
        without_file_paths(text).replace(FILE_PATH_TOKEN, "<path>")
    }

    #[test]
    fn replaces_script_file_paths() {
        assert_eq!(
            normalize(
                r#"import("./one-BrAf3own.js");const d=["assets/one-BrAf3own.js","https://cdn.example.com/a/b-X_1.mjs"];
//# sourceMappingURL=index-C3e2Htc9.js.map"#
            ),
            r#"import("<path>");const d=["<path>","https:<path>"];
//# sourceMappingURL=<path>.map"#
        );
        // A hash in a directory name is part of the path.
        assert_eq!(
            normalize(r#"import("../Bx9_a1c2/one.cjs")"#),
            r#"import("<path>")"#
        );
    }

    #[test]
    fn leaves_other_extensions_and_bare_extensions_alone() {
        let text = r#"["index.json","index.jsx","a.js_b",".js",x.jsonp,"js"]"#;
        assert_eq!(normalize(text), text);
        assert!(matches!(without_file_paths(text), Cow::Borrowed(_)));
    }

    #[test]
    fn handles_repeated_extensions_and_multibyte_text() {
        assert_eq!(normalize("a.jsx.js x.js.map"), "<path> <path>.map");
        assert_eq!(normalize("é日.js 😀 é.mjs"), "<path> 😀 <path>");
        // An emoji is not a path character, so the path starts after it.
        assert_eq!(normalize("😀js.js"), "😀<path>");
    }

    #[test]
    fn replaces_only_the_file_field_of_a_map() {
        // A source can share a chunk's name, and frames resolve to it, so it stays.
        let mut map: SourceMapContent = serde_json::from_value(serde_json::json!({
            "version": 3,
            "file": "assets/index.js",
            "sources": ["../src/index.js"],
            "mappings": "AAAA",
        }))
        .expect("Failed to build SourceMapContent");
        without_file_path_in_file_field(&mut map);

        assert_eq!(map.fields["file"], FILE_PATH_TOKEN);
        assert_eq!(
            map.fields["sources"],
            serde_json::json!(["../src/index.js"])
        );
    }
}
