use crate::{
    api::symbol_sets::SymbolSetUpload,
    sourcemaps::{
        args::ReleaseMode,
        content::{get_injected_release_id, MinifiedSourceFile, SourceMapFile},
    },
    utils::files::content_hash,
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

impl SourcePair {
    /// Turn the pair into an upload payload. The payload always carries the injected artifact;
    /// only the content hash depends on the mode.
    ///
    /// In event mode the hash is computed over the pair with the injection undone (snippet and
    /// chunk-id comment removed, sourcemap adjustment reversed), because the injected bytes vary
    /// while the chunk id does not: the embedded release id changes every release, and a chunk
    /// injected before a release could be resolved carries a shorter snippet (and a differently
    /// adjusted sourcemap) than the same chunk after a later run adds the release. The server
    /// keys its skip-or-conflict decision on this hash per chunk id, so any injection-state
    /// dependence turns an unchanged chunk into a `content_hash_mismatch` rejection.
    ///
    /// In symbol-set mode no hash is set and the upload layer hashes the raw payload, matching
    /// the hashes the server already stores for previous uploads.
    pub fn into_upload(mut self, release_mode: ReleaseMode) -> Result<SymbolSetUpload> {
        let chunk_id = self
            .get_chunk_id()
            .ok_or_else(|| anyhow!("Chunk ID not found"))?;
        let release_id = self.sourcemap.get_release_id();
        let source_content = self.source.inner.content.clone();
        let sourcemap_content = serde_json::to_string(&self.sourcemap.inner.content)?;

        let content_hash = match release_mode {
            ReleaseMode::Event => {
                self.remove_chunk_id(chunk_id.clone())?;
                let pristine_map = serde_json::to_string(&self.sourcemap.inner.content)?;
                // JSON serialization never contains a raw NUL, so it unambiguously separates
                // the parts (same framing as `stable_chunk_id`).
                Some(content_hash([
                    self.source.inner.content.as_bytes(),
                    b"\0".as_slice(),
                    pristine_map.as_bytes(),
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
