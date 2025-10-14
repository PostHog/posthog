use anyhow::{Ok, Result};
use clap::Subcommand;
use core::str;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use std::collections::BTreeMap;
use std::str::Lines;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};
use tracing::debug;
use walkdir::DirEntry;

pub mod constant;
pub mod inject;
pub mod source_pair;
pub mod upload;

use crate::sourcemaps::inject::InjectArgs;
use crate::sourcemaps::upload::UploadArgs;
use crate::utils::files::SourceFile;

#[derive(Subcommand)]
pub enum SourcemapCommand {
    /// Inject each bundled chunk with a posthog chunk ID
    Inject(InjectArgs),
    /// Upload the bundled chunks to PostHog
    Upload(UploadArgs),
    /// Run inject and upload in one command
    Process(UploadArgs),
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SourceMapChunkId {
    pub chunk_id: Option<String>,
    #[serde(flatten)]
    fields: BTreeMap<String, Value>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SourceMapContent {
    pub chunk_id: Option<String>,
    #[serde(flatten)]
    pub fields: HashMap<String, Value>,
}

pub fn get_sourcemap_reference(lines: Lines) -> Result<Option<String>> {
    for line in lines.rev() {
        if line.starts_with("//# sourceMappingURL=") || line.starts_with("//@ sourceMappingURL=") {
            let url = str::from_utf8(&line.as_bytes()[21..])?.trim().to_owned();
            let decoded_url = urlencoding::decode(&url)?;
            return Ok(Some(decoded_url.into_owned()));
        }
    }
    Ok(None)
}

pub fn get_sourcemap_path(source: &SourceFile) -> Result<Option<PathBuf>> {
    match get_sourcemap_reference(source.content.lines())? {
        Some(url) => {
            let sourcemap_path = source
                .path
                .parent()
                .map(|p| p.join(&url))
                .unwrap_or_else(|| PathBuf::from(&url));
            debug!("Found sourcemap path: {}", sourcemap_path.display());
            Ok(Some(sourcemap_path))
        }
        None => {
            let sourcemap_path = guess_sourcemap_path(&source.path);
            debug!("Guessed sourcemap path: {}", sourcemap_path.display());
            if sourcemap_path.exists() {
                Ok(Some(sourcemap_path))
            } else {
                Ok(None)
            }
        }
    }
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

fn is_javascript_file(entry: &DirEntry) -> bool {
    entry.file_type().is_file()
        && entry
            .path()
            .extension()
            .is_some_and(|ext| ext == "js" || ext == "mjs" || ext == "cjs")
}
