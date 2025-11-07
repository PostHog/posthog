use std::path::PathBuf;

use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::content::{MinifiedSourceFile, SourceMapFile},
};
use anyhow::{anyhow, bail, Context, Result};
use globset::{Glob, GlobSetBuilder};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use tracing::{info, warn};
use walkdir::{DirEntry, WalkDir};

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

    pub fn has_release_id(&self) -> bool {
        self.get_release_id().is_some()
    }

    pub fn get_release_id(&self) -> Option<String> {
        self.sourcemap.get_release_id()
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
        self.add_chunk_id(new_chunk_id)?;
        Ok(())
    }

    pub fn add_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        if self.has_chunk_id() {
            return Err(anyhow!("Chunk ID already set"));
        }

        let adjustment = self.source.set_chunk_id(&chunk_id)?;
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
    directory: &PathBuf,
    ignore_globs: &[String],
    matcher: impl Fn(&DirEntry) -> bool,
    prefix: &Option<String>,
) -> Result<Vec<SourcePair>> {
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
        .filter(matcher)
        .map(|e| e.path().canonicalize())
    {
        let entry_path = entry_path?;

        if set.is_match(&entry_path) {
            info!("skip [ignored]: {}", entry_path.display());
            continue;
        }

        let source = MinifiedSourceFile::load(&entry_path)?;
        let sourcemap_path = source.get_sourcemap_path(prefix)?;

        let Some(path) = sourcemap_path else {
            warn!("skip [no sourcemap]: {}", entry_path.display());
            continue;
        };

        info!("new pair: {}", entry_path.display());
        let sourcemap = SourceMapFile::load(&path).context(format!("reading {path:?}"))?;
        pairs.push(SourcePair { source, sourcemap });
    }

    info!("found {} pairs", pairs.len());

    Ok(pairs)
}

impl TryInto<SymbolSetUpload> for SourcePair {
    type Error = anyhow::Error;

    fn try_into(self) -> Result<SymbolSetUpload> {
        let chunk_id = self
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
