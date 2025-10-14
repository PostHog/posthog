use std::path::PathBuf;

use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::{
        constant::{CHUNKID_COMMENT_PREFIX, CHUNKID_PLACEHOLDER, CODE_SNIPPET_TEMPLATE},
        get_sourcemap_path, is_javascript_file, SourceMapChunkId,
    },
    utils::files::SourceFile,
};
use anyhow::{anyhow, bail, Context, Result};
use globset::{Glob, GlobSetBuilder};
use magic_string::{GenerateDecodedMapOptions, MagicString};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use sourcemap::SourceMap;
use tracing::{info, warn};
use walkdir::WalkDir;

// Source pairs are the fundamental unit of a frontend symbol set
pub struct SourcePair {
    pub chunk_id: Option<String>,

    pub source: SourceFile,
    pub sourcemap: SourceFile,
}

impl SourcePair {
    pub fn has_chunk_id(&self) -> bool {
        self.chunk_id.is_some()
    }

    pub fn set_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        if self.has_chunk_id() {
            return Err(anyhow!("Chunk ID already set"));
        }
        let (new_source_content, source_adjustment) = {
            // Update source content with chunk ID
            let source_content = &self.source.content;
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

        let new_sourcemap = {
            // Update the sourcemap with the new mappings
            let mut original_sourcemap =
                match sourcemap::decode_slice(self.sourcemap.content.as_bytes())
                    .map_err(|err| anyhow!("Failed to parse sourcemap: {}", err))?
                {
                    sourcemap::DecodedMap::Regular(map) => map,
                    sourcemap::DecodedMap::Index(index_map) => index_map
                        .flatten()
                        .map_err(|err| anyhow!("Failed to parse sourcemap: {}", err))?,
                    sourcemap::DecodedMap::Hermes(_) => {
                        anyhow::bail!("Hermes source maps are not supported")
                    }
                };

            original_sourcemap.adjust_mappings(&source_adjustment);

            let mut new_sourcemap_bytes = Vec::new();
            original_sourcemap.to_writer(&mut new_sourcemap_bytes)?;

            let mut sourcemap_chunk: SourceMapChunkId =
                serde_json::from_slice(&new_sourcemap_bytes)?;
            sourcemap_chunk.chunk_id = Some(chunk_id.clone());
            sourcemap_chunk
        };

        self.chunk_id = Some(chunk_id.clone());
        self.source.content = new_source_content;
        self.sourcemap.content = serde_json::to_string(&new_sourcemap)?;
        Ok(())
    }

    pub fn save(&self) -> Result<()> {
        self.source.save(None)?;
        self.sourcemap.save(None)?;
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
    for entry in WalkDir::new(directory).into_iter().filter_map(|e| e.ok()) {
        let entry_path = entry.path().canonicalize()?;

        if set.is_match(&entry_path) {
            info!(
                "Skipping because it matches an ignored glob: {}",
                entry_path.display()
            );
            continue;
        } else if is_javascript_file(&entry) {
            info!("Processing file: {}", entry_path.display());
            let source = SourceFile::load(&entry_path)?;
            let sourcemap_path = get_sourcemap_path(&source)?;
            if let Some(path) = sourcemap_path {
                let sourcemap = SourceFile::load(&path).context(format!("reading {path:?}"))?;
                let chunk_id = get_chunk_id(&sourcemap);
                pairs.push(SourcePair {
                    chunk_id,
                    source,
                    sourcemap,
                });
            } else {
                warn!("No sourcemap file found for file {}", entry_path.display());
            }
        }
    }
    Ok(pairs)
}

impl TryInto<SymbolSetUpload> for SourcePair {
    type Error = anyhow::Error;

    fn try_into(self) -> Result<SymbolSetUpload> {
        let chunk_id = self.chunk_id.ok_or_else(|| anyhow!("Chunk ID not found"))?;
        let source_content = self.source.content;
        let sourcemap_content = self.sourcemap.content;
        let data = SourceAndMap {
            minified_source: source_content,
            sourcemap: sourcemap_content,
        };
        let data = write_symbol_data(data)?;
        Ok(SymbolSetUpload {
            chunk_id: (),
            release_id: (),
            data: (),
        })
    }
}
