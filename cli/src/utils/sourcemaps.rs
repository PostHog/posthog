use anyhow::{anyhow, bail, Ok, Result};
use core::str;
use magic_string::{GenerateDecodedMapOptions, MagicString};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sourcemap::SourceMap;
use std::collections::BTreeMap;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};
use tracing::{info, warn};
use walkdir::WalkDir;

use super::constant::{CHUNKID_COMMENT_PREFIX, CHUNKID_PLACEHOLDER, CODE_SNIPPET_TEMPLATE};

pub struct SourceFile {
    pub path: PathBuf,
    pub content: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SourceMapChunkId {
    chunk_id: Option<String>,
    #[serde(flatten)]
    fields: BTreeMap<String, Value>,
}

impl SourceFile {
    pub fn new(path: PathBuf, content: String) -> Self {
        SourceFile { path, content }
    }

    pub fn load(path: &PathBuf) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        Ok(SourceFile::new(path.clone(), content))
    }

    pub fn save(&self, dest: Option<PathBuf>) -> Result<()> {
        let final_path = dest.unwrap_or(self.path.clone());
        std::fs::write(&final_path, &self.content)?;
        Ok(())
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SourceMapContent {
    chunk_id: Option<String>,
    #[serde(flatten)]
    fields: HashMap<String, Value>,
}

pub struct SourcePair {
    pub chunk_id: Option<String>,

    pub source: SourceFile,
    pub sourcemap: SourceFile,
}

pub struct ChunkUpload {
    pub chunk_id: String,
    pub data: Vec<u8>,
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

    pub fn into_chunk_upload(self) -> Result<ChunkUpload> {
        let chunk_id = self.chunk_id.ok_or_else(|| anyhow!("Chunk ID not found"))?;
        let source_content = self.source.content;
        let sourcemap_content = self.sourcemap.content;
        let data = SourceAndMap {
            minified_source: source_content,
            sourcemap: sourcemap_content,
        };
        let data = write_symbol_data(data)?;
        Ok(ChunkUpload { chunk_id, data })
    }
}

pub fn read_pairs(directory: &PathBuf) -> Result<Vec<SourcePair>> {
    // Make sure the directory exists
    if !directory.exists() {
        bail!("Directory does not exist");
    }

    let mut pairs = Vec::new();
    for entry in WalkDir::new(directory).into_iter().filter_map(|e| e.ok()) {
        let entry_path = entry.path().canonicalize()?;
        if is_javascript_file(&entry_path) {
            info!("Processing file: {}", entry_path.display());
            let source = SourceFile::load(&entry_path)?;
            let mut sourcemap_path = guess_sourcemap_path(&source.path);
            
            // If guess_sourcemap_path doesn't find a file, try parsing the source
            if !sourcemap_path.exists() {
                if let Some(sourcemap_url) = get_sourcemap_path(&source.content) {
                    // Resolve the sourcemap URL relative to the source file
                    let source_dir = source.path.parent().unwrap_or(Path::new("."));
                    sourcemap_path = source_dir.join(sourcemap_url);
                }
            }
            
            if sourcemap_path.exists() {
                let sourcemap = SourceFile::load(&sourcemap_path)?;
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

pub fn get_chunk_id(sourcemap: &SourceFile) -> Option<String> {
    #[derive(Deserialize)]
    struct SourceChunkId {
        chunk_id: String,
    }
    serde_json::from_str(&sourcemap.content)
        .map(|chunk_id: SourceChunkId| chunk_id.chunk_id)
        .ok()
}

pub fn guess_sourcemap_path(path: &Path) -> PathBuf {
    // Try to resolve the sourcemap by adding .map to the path
    let mut sourcemap_path = path.to_path_buf();
    match path.extension() {
        Some(ext) => sourcemap_path.set_extension(format!("{}.map", ext.to_string_lossy())),
        None => sourcemap_path.set_extension("map"),
    };
    sourcemap_path
}

fn is_javascript_file(path: &Path) -> bool {
    path.extension()
        .map_or(false, |ext| ext == "js" || ext == "mjs" || ext == "cjs")
}

pub fn get_sourcemap_path(source: &str) -> Option<String> {
    let js_comment = Regex::new(r"(?m)\s*(?://(?P<single>.*)|/\*(?P<multi>.*?)\*/|/\*.*|$|(?P<code>[^/]+))").unwrap();
    let pattern = Regex::new(r"^[@#]\s*sourceMappingURL=(\S*?)\s*$").unwrap();
    
    let mut last_url: Option<String> = None;
    
    for line in source.lines() {
        let mut pos = 0;
        while pos < line.len() {
            if let Some(captures) = js_comment.captures(&line[pos..]) {
                let match_end = captures.get(0).unwrap().end();
                
                if let Some(single_comment) = captures.name("single") {
                    if let Some(url_match) = pattern.captures(single_comment.as_str()) {
                        last_url = url_match.get(1).map(|m| m.as_str().to_string());
                    }
                } else if let Some(multi_comment) = captures.name("multi") {
                    if let Some(url_match) = pattern.captures(multi_comment.as_str()) {
                        last_url = url_match.get(1).map(|m| m.as_str().to_string());
                    }
                } else if captures.name("code").is_some() {
                    last_url = None;
                }
                
                pos += match_end;
                if match_end == 0 {
                    break;
                }
            } else {
                break;
            }
        }
    }
    
    last_url
}
