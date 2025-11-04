use anyhow::{anyhow, bail, Result};
use magic_string::{GenerateDecodedMapOptions, MagicString};
use posthog_symbol_data::{write_symbol_data, HermesMap};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sourcemap::SourceMap;
use std::{collections::BTreeMap, path::PathBuf};
use tracing::info;

use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::constant::{CHUNKID_COMMENT_PREFIX, CHUNKID_PLACEHOLDER, CODE_SNIPPET_TEMPLATE},
    utils::files::SourceFile,
};

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceMapContent {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub release_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chunk_id: Option<String>,
    #[serde(flatten)]
    pub fields: BTreeMap<String, Value>,
}

pub struct SourceMapFile {
    pub inner: SourceFile<SourceMapContent>,
}

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

    pub fn get_release_id(&self) -> Option<String> {
        self.inner.content.release_id.clone()
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

        Ok(())
    }

    pub fn set_chunk_id(&mut self, chunk_id: Option<String>) {
        self.inner.content.chunk_id = chunk_id;
    }

    pub fn set_release_id(&mut self, release_id: Option<String>) {
        self.inner.content.release_id = release_id;
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

    pub fn set_chunk_id(&mut self, chunk_id: &str) -> Result<SourceMap> {
        let (new_source_content, source_adjustment) = {
            // Update source content with chunk ID
            let source_content = &self.inner.content;
            let mut magic_source = MagicString::new(source_content);
            let code_snippet = CODE_SNIPPET_TEMPLATE.replace(CHUNKID_PLACEHOLDER, chunk_id);
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
                info!("Found sourcemap at path: {}", path.display());
                return Ok(Some(path));
            }
        }

        Ok(None)
    }

    pub fn get_sourcemap_reference(&self) -> Result<Option<String>> {
        let patterns = ["//# sourceMappingURL=", "//@ sourceMappingURL="];
        let Some(found) = self.get_comment_value(&patterns) else {
            return Ok(None);
        };
        Ok(Some(urlencoding::decode(&found)?.into_owned()))
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

            let code_snippet = CODE_SNIPPET_TEMPLATE.replace(CHUNKID_PLACEHOLDER, &chunk_id);
            if let Some(code_snippet_start) = source_content.find(&code_snippet) {
                let code_snippet_end = code_snippet_start as i64 + code_snippet.len() as i64;
                magic_source
                    .remove(code_snippet_start as i64, code_snippet_end)
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

impl TryInto<SymbolSetUpload> for SourceMapFile {
    type Error = anyhow::Error;

    fn try_into(self) -> Result<SymbolSetUpload> {
        let chunk_id = self
            .get_chunk_id()
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
        })
    }
}
