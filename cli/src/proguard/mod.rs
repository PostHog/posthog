use std::path::PathBuf;

use crate::{api::symbol_sets::SymbolSetUpload, utils::files::SourceFile};
use anyhow::Result;
use clap::Subcommand;
use posthog_symbol_data::{write_symbol_data, ProguardMapping};

pub mod upload;

#[derive(Subcommand)]
pub enum ProguardSubcommand {
    /// Upload proguard mapping files
    Upload(upload::Args),
}

pub struct ProguardFile {
    pub inner: SourceFile<String>,
    pub release_id: Option<String>,
    pub map_id: String,
}

impl ProguardFile {
    pub fn new(path: &PathBuf, map_id: String) -> Result<Self> {
        let inner: SourceFile<String> = SourceFile::load(path)?;

        let map = proguard::ProguardMapping::new(inner.content.as_bytes());
        if !map.is_valid() {
            anyhow::bail!(
                "File at {} is not a valid proguard mapping file",
                path.display()
            )
        }

        Ok(Self {
            inner,
            release_id: None,
            map_id,
        })
    }
}

impl TryInto<SymbolSetUpload> for ProguardFile {
    type Error = anyhow::Error;

    fn try_into(self) -> Result<SymbolSetUpload> {
        let inner = self.inner;

        let data = write_symbol_data(ProguardMapping {
            content: inner.content,
        })?;

        Ok(SymbolSetUpload {
            chunk_id: self.map_id,
            release_id: self.release_id,
            data,
        })
    }
}
