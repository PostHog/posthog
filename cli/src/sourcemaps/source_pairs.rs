use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::{
        args::ReleaseMode,
        content::{get_injected_release_id, MinifiedSourceFile, SourceMapContent, SourceMapFile},
    },
    utils::files::content_hash,
};
use aho_corasick::{AhoCorasick, MatchKind};
use anyhow::{anyhow, Context, Result};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use serde_json::Value;
use std::{borrow::Cow, collections::BTreeSet};
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

/// Stands in for a chunk file name in the event-mode content hash. The control characters keep
/// it from colliding with anything a bundler writes.
const CHUNK_FILE_NAME_TOKEN: &str = "\u{1}chunk-file-name\u{1}";

/// The file names of the chunks in one upload, which the event-mode content hash leaves out.
///
/// With content-hashed file names (Vite's default) a chunk is renamed whenever its bytes change,
/// and in event mode every chunk carries the release id, so every chunk is renamed on every
/// release. The names end up inside the chunks: the map's `file` field and the
/// `sourceMappingURL` comment hold the chunk's own name, and an import of another chunk holds
/// that chunk's name. Hashing them would upload every unchanged chunk again on every release
/// (PostHog/posthog#105956).
///
/// Leaving them out of the minified source and the map's `file` field cannot keep a stored
/// symbol set that resolves frames differently. A frame resolves through the map's mappings and
/// through the scopes read from the minified source by position, and the hash still covers both:
/// a name whose length changes shifts the generated columns after it on its line, which the
/// mappings record. The rest of the map is hashed as it is, because `sources`, `names` and
/// `sourcesContent` are what frames resolve to, and a source file can share a chunk's name.
/// `@posthog/rollup-plugin` derives its chunk ids before the bundler turns imports into file
/// names, so one chunk id already stands for every build that differs only in those names.
#[derive(Debug, Default)]
pub struct ChunkFileNames {
    matcher: Option<AhoCorasick>,
}

impl ChunkFileNames {
    pub fn new<'a>(pairs: impl IntoIterator<Item = &'a SourcePair>) -> Result<Self> {
        Self::from_names(
            pairs
                .into_iter()
                .filter_map(|pair| pair.source.inner.path.file_name()?.to_str()),
        )
    }

    fn from_names<'a>(names: impl IntoIterator<Item = &'a str>) -> Result<Self> {
        let names: BTreeSet<&str> = names.into_iter().collect();
        if names.is_empty() {
            return Ok(Self::default());
        }
        // Leftmost-longest, so that of two names ending the same way the longer one wins.
        let matcher = AhoCorasick::builder()
            .match_kind(MatchKind::LeftmostLongest)
            .build(names)
            .context("failed to index chunk file names")?;
        Ok(Self {
            matcher: Some(matcher),
        })
    }

    /// Replace every chunk file name in `text` that stands on its own with the same token.
    fn normalize<'t>(&self, text: &'t str) -> Cow<'t, str> {
        let Some(matcher) = &self.matcher else {
            return Cow::Borrowed(text);
        };
        let mut normalized = String::new();
        let mut copied = 0;
        for found in matcher.find_iter(text) {
            if !stands_alone(text, found.start(), found.end()) {
                continue;
            }
            normalized.push_str(&text[copied..found.start()]);
            normalized.push_str(CHUNK_FILE_NAME_TOKEN);
            copied = found.end();
        }
        if normalized.is_empty() {
            return Cow::Borrowed(text);
        }
        normalized.push_str(&text[copied..]);
        Cow::Owned(normalized)
    }

    /// Replace the chunk file name in the map's `file` field, the only field that names the
    /// chunk rather than its sources.
    fn normalize_file_field(&self, map: &mut SourceMapContent) {
        if let Some(Value::String(file)) = map.fields.get_mut("file") {
            if let Cow::Owned(normalized) = self.normalize(file) {
                *file = normalized;
            }
        }
    }
}

/// Whether the name at `start..end` is not part of a longer one: `index-C3e2Htc9.js` stands alone
/// in `"./index-C3e2Htc9.js"` and `index-C3e2Htc9.js.map`, but not in `my-index-C3e2Htc9.js` or
/// `index-C3e2Htc9.jsx`.
fn stands_alone(text: &str, start: usize, end: usize) -> bool {
    let continues_name = |c: char| c.is_alphanumeric() || matches!(c, '_' | '$' | '-' | '~');
    let before = text[..start].chars().next_back();
    let after = text[end..].chars().next();
    !before.is_some_and(|c| continues_name(c) || c == '.') && !after.is_some_and(continues_name)
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
    /// The hash also leaves out the file names of the chunks in the upload, `chunk_file_names`,
    /// which change with every release when the bundler names chunks by content (see
    /// `ChunkFileNames`).
    ///
    /// In symbol-set mode no hash is set and the upload layer hashes the raw payload, matching
    /// the hashes the server already stores for previous uploads.
    pub fn into_upload(
        mut self,
        release_mode: ReleaseMode,
        chunk_file_names: &ChunkFileNames,
    ) -> Result<SymbolSetUpload> {
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
                chunk_file_names.normalize_file_field(&mut self.sourcemap.inner.content);
                let pristine_map = serde_json::to_string(&self.sourcemap.inner.content)?;
                let pristine_source = chunk_file_names.normalize(&self.source.inner.content);
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

    fn normalize(names: &[&str], text: &str) -> String {
        ChunkFileNames::from_names(names.iter().copied())
            .expect("Failed to index chunk file names")
            .normalize(text)
            .replace(CHUNK_FILE_NAME_TOKEN, "<name>")
    }

    #[test]
    fn normalizes_names_that_stand_alone() {
        assert_eq!(
            normalize(
                &["index-C3e2Htc9.js", "one-BrAf3own.js"],
                r#"import("./one-BrAf3own.js");const d=["assets/one-BrAf3own.js"];
//# sourceMappingURL=index-C3e2Htc9.js.map"#,
            ),
            r#"import("./<name>");const d=["assets/<name>"];
//# sourceMappingURL=<name>.map"#
        );
    }

    #[test]
    fn normalizes_only_the_file_field_of_a_map() {
        // A source can share a chunk's name, and frames resolve to it, so it stays.
        let mut map: SourceMapContent = serde_json::from_value(serde_json::json!({
            "version": 3,
            "file": "assets/index.js",
            "sources": ["../src/index.js"],
            "mappings": "AAAA",
        }))
        .expect("Failed to build SourceMapContent");
        ChunkFileNames::from_names(["index.js"])
            .expect("Failed to index chunk file names")
            .normalize_file_field(&mut map);

        assert_eq!(
            map.fields["file"],
            format!("assets/{CHUNK_FILE_NAME_TOKEN}").as_str()
        );
        assert_eq!(
            map.fields["sources"],
            serde_json::json!(["../src/index.js"])
        );
    }

    #[test]
    fn leaves_names_inside_longer_names_alone() {
        let text = r#"["my-index.js","index.json","index.jsx","vendor.index.js"]"#;
        assert_eq!(normalize(&["index.js"], text), text);
        // Of two names ending the same way, the longer one is replaced whole.
        assert_eq!(
            normalize(
                &["index.js", "my-index.js"],
                r#"["my-index.js","index.js"]"#
            ),
            r#"["<name>","<name>"]"#
        );
    }

    #[test]
    fn without_names_borrows_the_text() {
        assert!(matches!(
            ChunkFileNames::default().normalize("import(\"./one.js\")"),
            Cow::Borrowed(_)
        ));
    }
}
