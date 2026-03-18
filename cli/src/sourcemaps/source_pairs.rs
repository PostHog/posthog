use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::content::{MinifiedSourceFile, SourceMapFile},
};
use anyhow::{anyhow, Context, Result};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
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

    pub fn has_release_id(&self) -> bool {
        self.sourcemap.has_release_id()
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
    selection: impl Iterator<Item = DirEntry>,
    prefix: &Option<String>,
) -> Vec<SourcePair> {
    let pairs = selection
        .filter_map(|entry| {
            let path = entry.path();
            let entry_path = path
                .canonicalize()
                .context("failed to canonicalize path")
                .map_err(|e| warn!("skip: {e:?}"))
                .ok()?;
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
