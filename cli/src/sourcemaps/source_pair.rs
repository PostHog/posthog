use std::{collections::BTreeMap, path::PathBuf};

use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::constant::{CHUNKID_COMMENT_PREFIX, CHUNKID_PLACEHOLDER, CODE_SNIPPET_TEMPLATE},
    utils::files::{is_javascript_file, SourceFile},
};
use anyhow::{anyhow, bail, Context, Result};
use globset::{Glob, GlobSetBuilder};
use magic_string::{GenerateDecodedMapOptions, MagicString};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sourcemap::SourceMap;
use tracing::{info, warn};
use walkdir::WalkDir;

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SourceMapContent {
    pub release_id: Option<String>,
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

// Source pairs are the fundamental unit of a frontend symbol set
pub struct SourcePair {
    pub source: MinifiedSourceFile,
    pub sourcemap: SourceMapFile,
}

impl SourcePair {
    pub fn new(source: MinifiedSourceFile, sourcemap: SourceMapFile) -> Result<Self> {
        if sourcemap.get_chunk_id() != source.get_chunk_id() {
            anyhow::bail!(
                "Source chunk ID and sourcemap chunk ID disagree. Try re-running injection"
            )
        }

        Ok(Self { source, sourcemap })
    }

    pub fn has_chunk_id(&self) -> bool {
        self.sourcemap.get_chunk_id().is_some()
    }

    pub fn has_release_id(&self) -> bool {
        self.sourcemap.get_release_id().is_some()
    }

    pub fn set_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        if self.has_chunk_id() {
            return Err(anyhow!("Chunk ID already set"));
        }

        let adjustment = self.source.set_chunk_id(&chunk_id)?;
        self.sourcemap.apply_adjustment(adjustment)?;
        self.sourcemap.set_chunk_id(chunk_id);
        Ok(())
    }

    pub fn set_release_id(&mut self, release_id: String) {
        self.sourcemap.set_release_id(release_id);
    }

    pub fn save(&self) -> Result<()> {
        self.source.save()?;
        self.sourcemap.save()?;
        Ok(())
    }
}

pub fn read_pairs(directory: &PathBuf, ignore_globs: &[String]) -> Result<Vec<SourcePair>> {
    // Make sure the directory exists
    if !directory.exists() {
        bail!("Directory does not exist");
    }

    let mut builder = GlobSetBuilder::new();
    for glob in ignore_globs {
        builder.add(Glob::new(glob)?);
    }
    let set: globset::GlobSet = builder.build()?;

    let mut pairs = Vec::new();

    for entry_path in WalkDir::new(directory)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(is_javascript_file)
        .map(|e| e.path().canonicalize())
    {
        let entry_path = entry_path?;

        if set.is_match(&entry_path) {
            info!(
                "Skipping because it matches an ignored glob: {}",
                entry_path.display()
            );
            continue;
        }

        info!("Processing file: {}", entry_path.display());
        let source = MinifiedSourceFile::load(&entry_path)?;
        let sourcemap_path = source.get_sourcemap_path()?;

        let Some(path) = sourcemap_path else {
            warn!(
                "No sourcemap file found for file {}, skipping",
                entry_path.display()
            );
            continue;
        };

        let sourcemap = SourceMapFile::load(&path).context(format!("reading {path:?}"))?;
        pairs.push(SourcePair { source, sourcemap });
    }
    Ok(pairs)
}

impl TryInto<SymbolSetUpload> for SourcePair {
    type Error = anyhow::Error;

    fn try_into(self) -> Result<SymbolSetUpload> {
        let chunk_id = self
            .sourcemap
            .get_chunk_id()
            .ok_or_else(|| anyhow!("Chunk ID not found"))?;
        let source_content = self.source.inner.content;
        let sourcemap_content = serde_json::to_string(&self.sourcemap.inner.content)?;
        let data = SourceAndMap {
            minified_source: source_content,
            sourcemap: sourcemap_content,
        };

        let data = write_symbol_data(data)?;

        Ok(SymbolSetUpload {
            chunk_id,
            data,
            release_id: self.sourcemap.get_release_id(),
        })
    }
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
            let mut original_sourcemap = match sourcemap::decode_slice(content.as_slice())
                .map_err(|err| anyhow!("Failed to parse sourcemap: {}", err))?
            {
                sourcemap::DecodedMap::Regular(map) => map,
                sourcemap::DecodedMap::Index(index_map) => index_map
                    .flatten()
                    .map_err(|err| anyhow!("Failed to parse sourcemap: {}", err))?,
                sourcemap::DecodedMap::Hermes(_) => {
                    // TODO(olly) - YES THEY ARE!!!!! WOOOOOOO!!!!! YIPEEEEEEEE!!!
                    anyhow::bail!("Hermes source maps are not supported")
                }
            };

            original_sourcemap.adjust_mappings(&adjustment);

            // I mean if we've got the bytes allocated already, why not use 'em
            let mut content = content;
            content.clear();
            original_sourcemap.to_writer(&mut content)?;

            serde_json::from_slice(&content)?
        };

        let mut old_content = std::mem::replace(&mut self.inner.content, new_content);
        self.inner.content.chunk_id = old_content.chunk_id.take();
        self.inner.content.release_id = old_content.release_id.take();

        Ok(())
    }

    pub fn set_chunk_id(&mut self, chunk_id: String) {
        self.inner.content.chunk_id = Some(chunk_id);
    }

    pub fn set_release_id(&mut self, release_id: String) {
        self.inner.content.release_id = Some(release_id);
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
        let patterns = ["//#chunk_id"];
        self.get_comment_value(&patterns)
    }

    pub fn set_chunk_id(&mut self, chunk_id: &str) -> Result<SourceMap> {
        let (new_source_content, source_adjustment) = {
            // Update source content with chunk ID
            let source_content = &self.inner.content;
            let mut magic_source = MagicString::new(source_content);
            let code_snippet = CODE_SNIPPET_TEMPLATE.replace(CHUNKID_PLACEHOLDER, &chunk_id);
            magic_source
                .prepend(&code_snippet)
                .map_err(|err| anyhow!("Failed to prepend code snippet: {}", err))?;
            let chunk_comment = CHUNKID_COMMENT_PREFIX.replace(CHUNKID_PLACEHOLDER, &chunk_id);
            magic_source
                .append(&chunk_comment)
                .map_err(|err| anyhow!("Failed to append chunk comment: {}", err))?;
            let adjustment = magic_source
                .generate_map(GenerateDecodedMapOptions {
                    include_content: true,
                    ..Default::default()
                })
                .map_err(|err| anyhow!("Failed to generate source map: {}", err))?;
            let adjustment_sourcemap = SourceMap::from_slice(
                adjustment
                    .to_string()
                    .map_err(|err| anyhow!("Failed to serialize source map: {}", err))?
                    .as_bytes(),
            )
            .map_err(|err| anyhow!("Failed to parse adjustment sourcemap: {}", err))?;
            (magic_source.to_string(), adjustment_sourcemap)
        };

        self.inner.content = new_source_content;
        Ok(source_adjustment)
    }

    pub fn get_sourcemap_path(&self) -> Result<Option<PathBuf>> {
        match self.get_sourcemap_reference()? {
            // If we've got a reference, use it
            Some(filename) => {
                let sourcemap_path = self
                    .inner
                    .path
                    .parent()
                    .map(|p| p.join(&filename))
                    .unwrap_or_else(|| PathBuf::from(&filename));
                Ok(Some(sourcemap_path))
            }
            // If we don't, try guessing
            None => {
                let mut sourcemap_path = self.inner.path.to_path_buf();
                match sourcemap_path.extension() {
                    Some(ext) => {
                        sourcemap_path.set_extension(format!("{}.map", ext.to_string_lossy()))
                    }
                    None => sourcemap_path.set_extension("map"),
                };
                if sourcemap_path.exists() {
                    info!("Guessed sourcemap path: {}", sourcemap_path.display());
                    Ok(Some(sourcemap_path))
                } else {
                    warn!("Could not find sourcemap for {}", self.inner.path.display());
                    Ok(None)
                }
            }
        }
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
}
