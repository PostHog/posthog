use anyhow::{anyhow, bail, Result};
use magic_string::{GenerateDecodedMapOptions, MagicString};
use posthog_symbol_data::{write_symbol_data, HermesMap};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sourcemap::SourceMap;
use std::{collections::BTreeMap, path::PathBuf};

use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::constant::{
        CHUNKID_COMMENT_PREFIX, CHUNKID_PLACEHOLDER, CODE_SNIPPET_TEMPLATE,
        CODE_SNIPPET_WITH_RELEASE_TEMPLATE, QUOTED_CHUNKID_PLACEHOLDER, RELEASE_ID_PLACEHOLDER,
    },
    utils::files::SourceFile,
};

/// Build the injected IIFE for a chunk. Both ids are filled in as JSON-encoded string literals,
/// so quotes/backslashes in the values can't break out of the snippet — chunk ids matter too,
/// since re-injection reuses whatever the `//# chunkId=` comment carries.
fn build_code_snippet(chunk_id: &str, release_id: Option<&str>) -> Result<String> {
    let Some(release_id) = release_id else {
        return substitute_chunk_id(CODE_SNIPPET_TEMPLATE, chunk_id);
    };
    Ok(
        substitute_chunk_id(CODE_SNIPPET_WITH_RELEASE_TEMPLATE, chunk_id)?
            .replace(RELEASE_ID_PLACEHOLDER, &serde_json::to_string(release_id)?),
    )
}

/// Fill a snippet template's quoted chunk-id placeholder with the JSON-encoded id. Every site
/// that renders or searches for an injected snippet must encode the same way, or ids that
/// need escaping would fail to round-trip through detection and removal.
fn substitute_chunk_id(template: &str, chunk_id: &str) -> Result<String> {
    Ok(template.replace(
        QUOTED_CHUNKID_PLACEHOLDER,
        &serde_json::to_string(chunk_id)?,
    ))
}

struct ReleaseSnippetSpan {
    start: usize,
    end: usize,
    release_id_start: usize,
    release_id_end: usize,
}

/// Locate the release-variant snippet for `chunk_id` in `source`, if present.
fn find_release_snippet(source: &str, chunk_id: &str) -> Option<ReleaseSnippetSpan> {
    let (prefix, suffix) = CODE_SNIPPET_WITH_RELEASE_TEMPLATE
        .split_once(RELEASE_ID_PLACEHOLDER)
        .expect("release template has a release id placeholder");
    let suffix = substitute_chunk_id(suffix, chunk_id).ok()?;

    let start = source.find(prefix)?;
    let release_id_start = start + prefix.len();
    let release_id_len = source[release_id_start..].find(&suffix)?;
    // The span between prefix and suffix must be the injected release id — a short JSON
    // string literal. A distant suffix match means user code, not our snippet.
    if release_id_len > 256 {
        return None;
    }
    let release_id_end = release_id_start + release_id_len;

    Some(ReleaseSnippetSpan {
        start,
        end: release_id_end + suffix.len(),
        release_id_start,
        release_id_end,
    })
}

/// Read the release id embedded in the source's release-variant snippet, if any.
pub fn get_injected_release_id(source: &str, chunk_id: &str) -> Option<String> {
    let span = find_release_snippet(source, chunk_id)?;
    serde_json::from_str(&source[span.release_id_start..span.release_id_end]).ok()
}

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceMapContent {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub release_id: Option<String>,
    #[serde(alias = "chunkId", skip_serializing_if = "Option::is_none")]
    pub chunk_id: Option<String>,
    /// Bundler-emitted ECMA-426 debug id. Kept separate from `chunk_id` so a bundler-stamped
    /// map isn't mistaken for one we already processed (which would skip the mapping
    /// adjustment on inject). Preserved on save for interop.
    #[serde(rename = "debugId", skip_serializing_if = "Option::is_none")]
    pub debug_id: Option<String>,
    #[serde(flatten)]
    pub fields: BTreeMap<String, Value>,
}

impl SourceMapContent {
    /// True when the sourcemap carries no symbolication payload — empty `mappings`,
    /// no `sources`, and no `names`. Such maps upload successfully but are useless
    /// for stack trace resolution, and usually indicate a bundler misconfiguration.
    ///
    /// Handles both source map flavors:
    /// - Plain maps: checks `mappings`, `sources`, `names` directly.
    /// - Indexed maps (Source Map Revision 3 "Index Map"): walks `sections[].map`
    ///   and reports empty only if every nested section is itself empty. Turbopack,
    ///   Metro, and webpack's ConcatSource all emit this format, and a shallow check
    ///   would skip large, valid maps that happen to have empty top-level fields.
    pub fn is_empty(&self) -> bool {
        let get = |k: &str| self.fields.get(k);
        is_map_empty(get)
    }
}

fn is_map_empty<'a>(get: impl Fn(&str) -> Option<&'a Value>) -> bool {
    let mappings_empty = get("mappings")
        .and_then(Value::as_str)
        .is_none_or(str::is_empty);
    let sources_empty = get("sources")
        .and_then(Value::as_array)
        .is_none_or(Vec::is_empty);
    let names_empty = get("names")
        .and_then(Value::as_array)
        .is_none_or(Vec::is_empty);
    let sections_empty = get("sections")
        .and_then(Value::as_array)
        .is_none_or(|s| s.iter().all(is_section_empty));
    mappings_empty && sources_empty && names_empty && sections_empty
}

fn is_section_empty(section: &Value) -> bool {
    let Some(map) = section.get("map").and_then(Value::as_object) else {
        return true;
    };
    is_map_empty(|k| map.get(k))
}

#[derive(Debug)]
pub struct SourceMapFile {
    pub inner: SourceFile<SourceMapContent>,
}

#[derive(Debug)]
pub struct MinifiedSourceFile {
    pub inner: SourceFile<String>,
}

impl SourceMapFile {
    pub fn load(path: &PathBuf) -> Result<Self> {
        let inner = SourceFile::load(path)?;

        Ok(Self { inner })
    }

    pub fn save(&self) -> Result<()> {
        self.inner.save(None)
    }

    pub fn get_chunk_id(&self) -> Option<String> {
        self.inner.content.chunk_id.clone()
    }

    pub fn get_debug_id(&self) -> Option<String> {
        self.inner.content.debug_id.clone()
    }

    /// The id this map's symbol set uploads under: our stamped chunk id when present, else a
    /// bundler-emitted debug id. Hermes maps built with Expo's tooling carry only the latter.
    pub fn get_upload_chunk_id(&self) -> Option<String> {
        self.get_chunk_id().or_else(|| self.get_debug_id())
    }

    pub fn get_release_id(&self) -> Option<String> {
        self.inner.content.release_id.clone()
    }

    pub fn has_release_id(&self) -> bool {
        self.get_release_id().is_some()
    }

    pub fn apply_adjustment(&mut self, adjustment: SourceMap) -> Result<()> {
        let new_content = {
            let content = serde_json::to_string(&self.inner.content)?.into_bytes();
            let mut map = sourcemap::decode_slice(content.as_slice())
                .map_err(|err| anyhow!("Failed to parse sourcemap: {err}"))?;

            // This looks weird. The reason we do it, is that we want `original` below
            // to be a &mut SourceMap. This is easy to do if it's a Regular, or Hermes
            // map, but if it's an Index map (Regular is already a SourceMap, so just
            // taking the &mut works, and Hermes maps impl DerefMut<Target = SourceMap>),
            // but for index maps, we have to flatten first, and that necessitates a Clone.
            // Doing that Clone in the match below and then trying to borrow a &mut to the
            // result of the Clone causes us to try and borrow something we immediately drop,
            // (the clone is done in the match arm scope, and then a ref to a local in that
            // scope is returned to the outer scope), so instead, we do the clone here if
            // we need to, and declare the index branch unreachable below.
            if let sourcemap::DecodedMap::Index(indexed) = &mut map {
                let replacement = indexed
                    .flatten()
                    .map_err(|err| anyhow!("Failed to flatten sourcemap: {err}"))?;

                map = sourcemap::DecodedMap::Regular(replacement);
            };

            let original = match &mut map {
                sourcemap::DecodedMap::Regular(m) => m,
                sourcemap::DecodedMap::Hermes(m) => m,
                sourcemap::DecodedMap::Index(_) => unreachable!(),
            };

            original.adjust_mappings(&adjustment);

            let mut content = content;
            content.clear();
            original.to_writer(&mut content)?;
            serde_json::from_slice(&content)?
        };

        let mut old_content = std::mem::replace(&mut self.inner.content, new_content);
        self.inner.content.chunk_id = old_content.chunk_id.take();
        self.inner.content.release_id = old_content.release_id.take();
        self.inner.content.debug_id = old_content.debug_id.take();
        // Preserve extension fields (e.g. x_org_dartlang_dart2js for Flutter/Dart minified name mapping)
        // Skip "sections" since that's specific to index sourcemaps which we flatten above
        for (key, value) in old_content.fields {
            if key != "sections" {
                self.inner.content.fields.entry(key).or_insert(value);
            }
        }

        Ok(())
    }

    pub fn set_chunk_id(&mut self, chunk_id: Option<String>) {
        self.inner.content.chunk_id = chunk_id;
    }

    pub fn set_release_id(&mut self, release_id: Option<String>) {
        self.inner.content.release_id = release_id;
    }

    pub fn is_empty(&self) -> bool {
        self.inner.content.is_empty()
    }
}

impl MinifiedSourceFile {
    pub fn load(path: &PathBuf) -> Result<Self> {
        let inner = SourceFile::load(path)?;

        Ok(Self { inner })
    }

    pub fn save(&self) -> Result<()> {
        self.inner.save(None)
    }

    pub fn get_chunk_id(&self) -> Option<String> {
        let patterns = ["//# chunkId="];
        self.get_comment_value(&patterns)
    }

    pub fn get_debug_id(&self) -> Option<String> {
        let patterns = ["//# debugId="];
        self.get_comment_value(&patterns)
    }

    pub fn set_chunk_id(&mut self, chunk_id: &str, release_id: Option<&str>) -> Result<SourceMap> {
        let (new_source_content, source_adjustment) = {
            // Update source content with chunk ID
            let source_content = &self.inner.content;
            let mut magic_source = MagicString::new(source_content);
            let code_snippet = build_code_snippet(chunk_id, release_id)?;
            magic_source
                .prepend(&code_snippet)
                .map_err(|err| anyhow!("Failed to prepend code snippet: {err}"))?;
            let chunk_comment = CHUNKID_COMMENT_PREFIX.replace(CHUNKID_PLACEHOLDER, chunk_id);
            magic_source
                .append(&chunk_comment)
                .map_err(|err| anyhow!("Failed to append chunk comment: {err}"))?;
            let adjustment = magic_source
                .generate_map(GenerateDecodedMapOptions {
                    include_content: true,
                    ..Default::default()
                })
                .map_err(|err| anyhow!("Failed to generate source map: {err}"))?;
            let adjustment_sourcemap = SourceMap::from_slice(
                adjustment
                    .to_string()
                    .map_err(|err| anyhow!("Failed to serialize source map: {err}"))?
                    .as_bytes(),
            )
            .map_err(|err| anyhow!("Failed to parse adjustment sourcemap: {err}"))?;
            (magic_source.to_string(), adjustment_sourcemap)
        };

        self.inner.content = new_source_content;
        Ok(source_adjustment)
    }

    pub fn get_sourcemap_path(&self, prefix: &Option<String>) -> Result<Option<PathBuf>> {
        let mut possible_paths = Vec::new();
        if let Some(filename) = self.get_sourcemap_reference()? {
            possible_paths.push(
                self.inner
                    .path
                    .parent()
                    .map(|p| p.join(&filename))
                    .unwrap_or_else(|| PathBuf::from(&filename)),
            );

            if let Some(prefix) = prefix {
                if let Some(filename) = filename.strip_prefix(prefix) {
                    possible_paths.push(
                        self.inner
                            .path
                            .parent()
                            .map(|p| p.join(filename))
                            .unwrap_or_else(|| PathBuf::from(&filename)),
                    );
                }

                if let Some(filename) = filename.strip_prefix(&format!("{prefix}/")) {
                    possible_paths.push(
                        self.inner
                            .path
                            .parent()
                            .map(|p| p.join(filename))
                            .unwrap_or_else(|| PathBuf::from(&filename)),
                    );
                }
            }
        };

        let mut guessed_path = self.inner.path.to_path_buf();
        match guessed_path.extension() {
            Some(ext) => guessed_path.set_extension(format!("{}.map", ext.to_string_lossy())),
            None => guessed_path.set_extension("map"),
        };
        possible_paths.push(guessed_path);

        for path in possible_paths.into_iter() {
            if path.exists() {
                return Ok(Some(path));
            }
        }

        Ok(None)
    }

    pub fn get_sourcemap_reference(&self) -> Result<Option<String>> {
        let found = if self.is_stylesheet() {
            css_sourcemap_reference(&self.inner.content)
        } else {
            self.inner.content.lines().rev().find_map(|line| {
                let line = line.trim();
                ["//# sourceMappingURL=", "//@ sourceMappingURL="]
                    .iter()
                    .find_map(|prefix| line.strip_prefix(prefix))
            })
        };

        Ok(found
            .map(|reference| urlencoding::decode(reference).map(|decoded| decoded.into_owned()))
            .transpose()?)
    }

    pub fn remove_sourcemap_reference(&mut self) -> bool {
        let range = if self.is_stylesheet() {
            css_sourcemap_reference_removal_range(&self.inner.content)
        } else {
            trailing_sourcemap_reference_range(&self.inner.content)
        };
        let Some(range) = range else {
            return false;
        };
        self.inner.content.replace_range(range, "");
        true
    }

    fn is_stylesheet(&self) -> bool {
        self.inner.path.extension().is_some_and(|ext| ext == "css")
    }

    fn get_comment_value(&self, patterns: &[&str]) -> Option<String> {
        for line in self.inner.content.lines().rev() {
            if let Some(val) = patterns
                // For each pattern passed
                .iter()
                // If the pattern matches
                .filter(|p| line.starts_with(*p))
                // And the line actually contains a key:value pair split by an equals
                .filter_map(|_| line.split_once('=').map(|s| s.1.to_string())) // And the split_once returns a Some
                // Return this value
                .next()
            {
                return Some(val);
            }
        }
        None
    }

    pub fn remove_chunk_id(&mut self, chunk_id: String) -> Result<SourceMap> {
        let (new_source_content, source_adjustment) = {
            // Update source content with chunk ID
            let source_content = &self.inner.content;
            let mut magic_source = MagicString::new(source_content);

            let chunk_comment = CHUNKID_COMMENT_PREFIX.replace(CHUNKID_PLACEHOLDER, &chunk_id);
            if let Some(chunk_comment_start) = source_content.find(&chunk_comment) {
                let chunk_comment_end = chunk_comment_start as i64 + chunk_comment.len() as i64;
                magic_source
                    .remove(chunk_comment_start as i64, chunk_comment_end)
                    .map_err(|err| anyhow!("Failed to remove chunk comment: {err}"))?;
            }

            let code_snippet = substitute_chunk_id(CODE_SNIPPET_TEMPLATE, &chunk_id)?;
            if let Some(code_snippet_start) = source_content.find(&code_snippet) {
                let code_snippet_end = code_snippet_start as i64 + code_snippet.len() as i64;
                magic_source
                    .remove(code_snippet_start as i64, code_snippet_end)
                    .map_err(|err| anyhow!("Failed to remove code snippet {err}"))?;
            } else if let Some(span) = find_release_snippet(source_content, &chunk_id) {
                magic_source
                    .remove(span.start as i64, span.end as i64)
                    .map_err(|err| anyhow!("Failed to remove code snippet {err}"))?;
            }

            let adjustment = magic_source
                .generate_map(GenerateDecodedMapOptions {
                    include_content: true,
                    ..Default::default()
                })
                .map_err(|err| anyhow!("Failed to generate source map: {err}"))?;

            let adjustment_sourcemap = SourceMap::from_slice(
                adjustment
                    .to_string()
                    .map_err(|err| anyhow!("Failed to serialize source map: {err}"))?
                    .as_bytes(),
            )
            .map_err(|err| anyhow!("Failed to parse adjustment sourcemap: {err}"))?;

            (magic_source.to_string(), adjustment_sourcemap)
        };

        self.inner.content = new_source_content;
        Ok(source_adjustment)
    }
}

const CSS_SOURCEMAP_REFERENCE_PREFIX: &str = "/*# sourceMappingURL=";

fn css_sourcemap_reference_range(line: &str) -> Option<std::ops::Range<usize>> {
    let bytes = line.as_bytes();
    let mut index = 0;
    let mut quote = None;
    let mut escaped = false;
    let mut found = None;

    while index < bytes.len() {
        if escaped {
            escaped = false;
            index += 1;
            continue;
        }

        if let Some(active_quote) = quote {
            if bytes[index] == b'\\' {
                escaped = true;
            } else if bytes[index] == active_quote {
                quote = None;
            }
            index += 1;
            continue;
        }

        if bytes[index] == b'\\' {
            escaped = true;
            index += 1;
            continue;
        }

        match bytes[index] {
            b'\'' | b'"' => {
                quote = Some(bytes[index]);
                index += 1;
            }
            b'/' if bytes.get(index + 1) == Some(&b'*') => {
                let comment_end = line[index + 2..].find("*/").map(|end| index + end + 4)?;
                if line[index..].starts_with(CSS_SOURCEMAP_REFERENCE_PREFIX) {
                    found = Some(index..comment_end);
                }
                index = comment_end;
            }
            _ => index += 1,
        }
    }

    found
}

fn css_sourcemap_reference(content: &str) -> Option<&str> {
    let range = css_sourcemap_reference_range(content)?;
    let reference_start = range.start + CSS_SOURCEMAP_REFERENCE_PREFIX.len();
    Some(content[reference_start..range.end - 2].trim_end())
}

fn css_sourcemap_reference_removal_range(content: &str) -> Option<std::ops::Range<usize>> {
    let comment_range = css_sourcemap_reference_range(content)?;
    let line_start = content[..comment_range.start]
        .rfind('\n')
        .map_or(0, |index| index + 1);
    let line_end = content[comment_range.end..]
        .find('\n')
        .map_or(content.len(), |index| comment_range.end + index + 1);

    if content[line_start..comment_range.start].trim().is_empty()
        && content[comment_range.end..line_end].trim().is_empty()
    {
        Some(line_start..line_end)
    } else {
        Some(comment_range)
    }
}

fn trailing_sourcemap_reference_range(content: &str) -> Option<std::ops::Range<usize>> {
    let mut line_start = 0;
    let mut lines = Vec::new();
    for line in content.split_inclusive('\n') {
        let line_end = line_start + line.len();
        lines.push((line_start, line_end, line));
        line_start = line_end;
    }

    for (line_start, line_end, line) in lines.into_iter().rev() {
        let trimmed_line = line.trim();
        if trimmed_line.is_empty()
            || trimmed_line.starts_with("//# chunkId=")
            || trimmed_line.starts_with("//# debugId=")
        {
            continue;
        }
        if trimmed_line.starts_with("//# sourceMappingURL=")
            || trimmed_line.starts_with("//@ sourceMappingURL=")
        {
            return Some(line_start..line_end);
        }
        return None;
    }

    None
}

impl TryInto<SymbolSetUpload> for SourceMapFile {
    type Error = anyhow::Error;

    fn try_into(self) -> Result<SymbolSetUpload> {
        let chunk_id = self
            .get_upload_chunk_id()
            .ok_or_else(|| anyhow!("Chunk ID not found"))?;

        let release_id = self.get_release_id();
        let sourcemap = self.inner.content;
        let content = serde_json::to_string(&sourcemap)?;
        if !sourcemap.fields.contains_key("x_hermes_function_offsets") {
            bail!("Map is not a hermes sourcemap - missing key x_hermes_function_offsets");
        }

        let data = HermesMap { sourcemap: content };

        let data = write_symbol_data(data)?;

        Ok(SymbolSetUpload {
            chunk_id,
            release_id,
            data,
            content_hash: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn content_from(value: Value) -> SourceMapContent {
        serde_json::from_value(value).expect("Failed to build SourceMapContent")
    }

    fn source_file(path: &str, content: &str) -> MinifiedSourceFile {
        MinifiedSourceFile {
            inner: SourceFile::new(PathBuf::from(path), content.to_string()),
        }
    }

    fn minified_source(content: &str) -> MinifiedSourceFile {
        source_file("chunk.js", content)
    }

    fn stylesheet_source(content: &str) -> MinifiedSourceFile {
        source_file("styles.css", content)
    }

    #[test]
    fn build_code_snippet_json_encodes_ids() {
        let hostile = r#"a");window.x=1;("b"#;
        let encoded = serde_json::to_string(hostile).unwrap();

        let plain = build_code_snippet(hostile, None).unwrap();
        let with_release = build_code_snippet(hostile, Some(hostile)).unwrap();

        assert!(plain.contains(&encoded), "snippet: {plain}");
        assert_eq!(
            with_release.matches(&encoded).count(),
            2,
            "snippet: {with_release}"
        );
    }

    #[test]
    fn get_injected_release_id_round_trips_escaped_ids() {
        // Ids that need JSON escaping must survive detection: the re-inject flow reads the
        // embedded release id back to decide whether to refresh the snippet.
        let chunk_id = r#"weird"chunk\id"#;
        let release_id = r#"rel"ease\id"#;
        let snippet = build_code_snippet(chunk_id, Some(release_id)).unwrap();

        assert_eq!(
            get_injected_release_id(&format!("{snippet}code();"), chunk_id).as_deref(),
            Some(release_id)
        );
    }

    #[test]
    fn is_empty_true_for_all_empty_fields() {
        let sm = content_from(json!({
            "version": 3,
            "file": "index-abc.js",
            "mappings": "",
            "names": [],
            "sources": [],
            "sourcesContent": [],
        }));
        assert!(sm.is_empty());
    }

    #[test]
    fn is_empty_true_when_fields_missing() {
        let sm = content_from(json!({
            "version": 3,
            "file": "index-abc.js",
        }));
        assert!(sm.is_empty());
    }

    #[test]
    fn is_empty_false_with_mappings_only() {
        let sm = content_from(json!({
            "version": 3,
            "mappings": "AAAA",
            "names": [],
            "sources": [],
        }));
        assert!(!sm.is_empty());
    }

    #[test]
    fn is_empty_false_with_sources_only() {
        let sm = content_from(json!({
            "version": 3,
            "mappings": "",
            "names": [],
            "sources": ["foo.ts"],
        }));
        assert!(!sm.is_empty());
    }

    #[test]
    fn is_empty_false_with_names_only() {
        let sm = content_from(json!({
            "version": 3,
            "mappings": "",
            "names": ["x"],
            "sources": [],
        }));
        assert!(!sm.is_empty());
    }

    #[test]
    fn is_empty_true_for_indexed_map_with_empty_sections_array() {
        // Turbopack emits this shape for thin App Router page wrappers.
        let sm = content_from(json!({
            "version": 3,
            "sources": [],
            "sections": [],
        }));
        assert!(sm.is_empty());
    }

    #[test]
    fn is_empty_false_for_indexed_map_with_non_empty_section() {
        // Turbopack's `[turbopack]_runtime.js.map` shape: top-level fields are
        // empty/absent but real mappings live under `sections[].map`.
        let sm = content_from(json!({
            "version": 3,
            "sources": [],
            "sections": [
                {
                    "offset": { "line": 17, "column": 0 },
                    "map": {
                        "version": 3,
                        "sources": ["turbopack:///[turbopack]/runtime-utils.ts"],
                        "mappings": "AAAA,SAAS",
                        "names": [],
                    }
                }
            ],
        }));
        assert!(!sm.is_empty());
    }

    #[test]
    fn is_empty_true_when_every_section_is_empty() {
        let sm = content_from(json!({
            "version": 3,
            "sections": [
                { "offset": { "line": 0, "column": 0 }, "map": { "version": 3, "sources": [], "mappings": "", "names": [] } },
                { "offset": { "line": 5, "column": 0 }, "map": { "version": 3, "sources": [], "mappings": "", "names": [] } },
            ],
        }));
        assert!(sm.is_empty());
    }

    #[test]
    fn is_empty_false_for_nested_indexed_map() {
        // Indexed maps can technically contain indexed maps. Rare but legal.
        let sm = content_from(json!({
            "version": 3,
            "sections": [
                {
                    "offset": { "line": 0, "column": 0 },
                    "map": {
                        "version": 3,
                        "sections": [
                            { "offset": { "line": 0, "column": 0 }, "map": {
                                "version": 3, "sources": ["a.ts"], "mappings": "AAAA", "names": []
                            }}
                        ]
                    }
                }
            ],
        }));
        assert!(!sm.is_empty());
    }

    #[test]
    fn debug_id_is_not_conflated_with_chunk_id_and_round_trips() {
        let sm = content_from(json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["a.ts"],
            "names": [],
            "debugId": "11111111-2222-4333-8444-555555555555",
        }));

        assert_eq!(
            sm.debug_id.as_deref(),
            Some("11111111-2222-4333-8444-555555555555")
        );
        assert!(sm.chunk_id.is_none());

        let out = serde_json::to_value(&sm).expect("Failed to serialize");
        assert_eq!(out["debugId"], "11111111-2222-4333-8444-555555555555");
        assert!(out.get("chunk_id").is_none());
    }

    #[test]
    fn hermes_upload_accepts_map_with_only_debug_id() {
        let file = SourceMapFile {
            inner: SourceFile::new(
                PathBuf::from("bundle.js.map"),
                content_from(json!({
                    "version": 3,
                    "mappings": "AAAA",
                    "sources": ["a.ts"],
                    "names": [],
                    "debugId": "11111111-2222-4333-8444-555555555555",
                    "x_hermes_function_offsets": {},
                })),
            ),
        };

        let upload: SymbolSetUpload = file.try_into().expect("Failed to convert to upload");
        assert_eq!(upload.chunk_id, "11111111-2222-4333-8444-555555555555");
    }

    #[test]
    fn hermes_upload_accepts_map_with_camel_case_chunk_id() {
        let file = SourceMapFile {
            inner: SourceFile::new(
                PathBuf::from("bundle.js.map"),
                content_from(json!({
                    "version": 3,
                    "mappings": "AAAA",
                    "sources": ["a.ts"],
                    "names": [],
                    "chunkId": "11111111-2222-4333-8444-555555555555",
                    "x_hermes_function_offsets": {},
                })),
            ),
        };

        let upload: SymbolSetUpload = file.try_into().expect("Failed to convert to upload");
        assert_eq!(upload.chunk_id, "11111111-2222-4333-8444-555555555555");
    }

    #[test]
    fn remove_sourcemap_reference_strips_standard_comment() {
        let mut source = minified_source("console.log(1);\n//# sourceMappingURL=chunk.js.map\n");

        assert!(source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, "console.log(1);\n");
    }

    #[test]
    fn remove_sourcemap_reference_strips_legacy_comment() {
        let mut source = minified_source("console.log(1);\r\n//@ sourceMappingURL=chunk.js.map");

        assert!(source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, "console.log(1);\r\n");
    }

    #[test]
    fn remove_sourcemap_reference_strips_css_comment() {
        let mut source =
            stylesheet_source(".app { color: black; }\n/*# sourceMappingURL=app.css.map*/\n");

        assert_eq!(
            source.get_sourcemap_reference().unwrap(),
            Some("app.css.map".to_string())
        );
        assert!(source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, ".app { color: black; }\n");
    }

    #[test]
    fn remove_sourcemap_reference_strips_inline_css_comment() {
        let mut source = stylesheet_source(
            ".app{content:\"/* not a comment */\"}/*# sourceMappingURL=app.css.map */\n",
        );

        assert_eq!(
            source.get_sourcemap_reference().unwrap(),
            Some("app.css.map".to_string())
        );
        assert!(source.remove_sourcemap_reference());
        assert_eq!(
            source.inner.content,
            ".app{content:\"/* not a comment */\"}\n"
        );
    }

    #[test]
    fn remove_sourcemap_reference_ignores_css_string_contents() {
        let original = ".example::after{content:\"/*# sourceMappingURL=app.css.map*/\"}\n";
        let mut source = stylesheet_source(original);

        assert_eq!(source.get_sourcemap_reference().unwrap(), None);
        assert!(!source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, original);
    }

    #[test]
    fn remove_sourcemap_reference_ignores_css_string_after_escaped_quote() {
        let original = ".foo\\'bar{content:\"x'/*# sourceMappingURL=victim.map*/\"}\n";
        let mut source = stylesheet_source(original);

        assert_eq!(source.get_sourcemap_reference().unwrap(), None);
        assert!(!source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, original);
    }

    #[test]
    fn remove_sourcemap_reference_ignores_continued_css_string_contents() {
        let original =
            ".example::after{content:\"before\\\n/*# sourceMappingURL=app.css.map*/\"}\n";
        let mut source = stylesheet_source(original);

        assert_eq!(source.get_sourcemap_reference().unwrap(), None);
        assert!(!source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, original);
    }

    #[test]
    fn remove_sourcemap_reference_ignores_javascript_template_contents() {
        let original = "const css = `body{}/*# sourceMappingURL=theme.css.map*/`;\n";
        let mut source = minified_source(original);

        assert_eq!(source.get_sourcemap_reference().unwrap(), None);
        assert!(!source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, original);
    }

    #[test]
    fn remove_sourcemap_reference_preserves_adjacent_css_license() {
        let mut source =
            stylesheet_source(".a{}/*# sourceMappingURL=app.css.map*/ /* license */\n");

        assert_eq!(
            source.get_sourcemap_reference().unwrap(),
            Some("app.css.map".to_string())
        );
        assert!(source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, ".a{} /* license */\n");
    }

    #[test]
    fn remove_sourcemap_reference_strips_css_comment_before_license() {
        let mut source = stylesheet_source(
            ".app{color:black}\n/*# sourceMappingURL=app.css.map */\n/* license */\n",
        );

        assert_eq!(
            source.get_sourcemap_reference().unwrap(),
            Some("app.css.map".to_string())
        );
        assert!(source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, ".app{color:black}\n/* license */\n");
    }

    #[test]
    fn remove_sourcemap_reference_strips_comment_with_injected_chunk_id() {
        let mut source = minified_source(
            "console.log(1);\n//# sourceMappingURL=chunk.js.map\n\n//# chunkId=00000",
        );

        assert!(source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, "console.log(1);\n\n//# chunkId=00000");
    }

    #[test]
    fn remove_sourcemap_reference_strips_comment_with_trailing_debug_id() {
        // sentry-cli appends its `//# debugId=` comment after the sourceMappingURL line, and
        // `--delete-after` must still find and strip the reference behind it.
        let mut source = minified_source(
            "console.log(1);\n//# sourceMappingURL=chunk.js.map\n//# debugId=00000",
        );

        assert!(source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, "console.log(1);\n//# debugId=00000");
    }

    #[test]
    fn remove_sourcemap_reference_leaves_non_trailing_comment() {
        let original = "console.log(1);\n//# sourceMappingURL=chunk.js.map\nconsole.log(2);\n";
        let mut source = minified_source(original);

        assert!(!source.remove_sourcemap_reference());
        assert_eq!(source.inner.content, original);
    }
}
