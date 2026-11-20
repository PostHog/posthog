// The parity tests compare the result with posthog-cli's for payloads on every boundary of the
// compressor, which holds the worker's zstd to posthog-cli's.

use anyhow::{anyhow, Result};
use posthog_symbol_data::{write_symbol_data, AppleDsym, ElfDebugInfo, HermesMap, ProguardMapping};
use serde::{Deserialize, Serialize};
use std::path::Path;

use crate::{node, upload::content_hash};

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Proguard,
    Hermes,
    Dsym,
    Elf,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Wrapped {
    content_hash: String,
    size: usize,
}

pub fn wrap(path: &Path, kind: Kind, out: Option<&Path>) -> Result<Wrapped> {
    let data = node::read(path).map_err(|message| anyhow!(message))?;
    let text = |data: Vec<u8>| node::utf8(data).map_err(|message| anyhow!(message));

    let container = match kind {
        Kind::Proguard => write_symbol_data(ProguardMapping {
            content: text(data)?,
        })?,
        Kind::Hermes => write_symbol_data(HermesMap {
            sourcemap: text(data)?,
        })?,
        Kind::Dsym => write_symbol_data(AppleDsym { data })?,
        Kind::Elf => write_symbol_data(ElfDebugInfo { data })?,
    };
    if let Some(out) = out {
        std::fs::write(out, &container)
            .map_err(|error| anyhow!(node::message(&error, "open", out)))?;
    }

    Ok(Wrapped {
        content_hash: content_hash([&container]),
        size: container.len(),
    })
}
