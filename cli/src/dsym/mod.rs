use std::path::{Path, PathBuf};

use crate::api::symbol_sets::SymbolSetUpload;
use anyhow::{anyhow, Result};
use clap::Subcommand;

pub mod upload;

#[derive(Subcommand)]
pub enum DsymSubcommand {
    /// Upload iOS/macOS dSYM files
    Upload(upload::Args),
}

/// Represents a dSYM bundle ready for upload
pub struct DsymFile {
    /// The UUIDs of the dSYM (one per architecture, used as chunk_id for matching)
    pub uuids: Vec<String>,
    /// The zipped dSYM bundle data
    pub data: Vec<u8>,
    /// Optional release ID
    pub release_id: Option<String>,
}

impl DsymFile {
    /// Create a new DsymFile from a .dSYM bundle path
    pub fn new(path: &PathBuf) -> Result<Self> {
        // Validate it's a dSYM bundle
        if !path.is_dir() {
            anyhow::bail!("Path {} is not a directory", path.display());
        }

        let extension = path.extension().and_then(|e| e.to_str());
        if extension != Some("dSYM") {
            anyhow::bail!(
                "Path {} is not a dSYM bundle (expected .dSYM extension)",
                path.display()
            );
        }

        // Extract UUIDs from the dSYM (one per architecture for universal binaries)
        let uuids = extract_dsym_uuids(path)?;

        // Zip the dSYM bundle
        let data = zip_dsym_bundle(path)?;

        Ok(Self {
            uuids,
            data,
            release_id: None,
        })
    }
}

impl DsymFile {
    /// Convert to SymbolSetUploads (one per UUID/architecture)
    pub fn into_uploads(self) -> Vec<SymbolSetUpload> {
        self.uuids
            .into_iter()
            .map(|uuid| SymbolSetUpload {
                chunk_id: uuid,
                release_id: self.release_id.clone(),
                data: self.data.clone(),
            })
            .collect()
    }
}

/// Extract all UUIDs from a dSYM bundle using dwarfdump
/// Universal binaries have multiple UUIDs (one per architecture)
fn extract_dsym_uuids(dsym_path: &PathBuf) -> Result<Vec<String>> {
    use std::process::Command;

    let output = Command::new("dwarfdump")
        .arg("--uuid")
        .arg(dsym_path)
        .output()
        .map_err(|e| anyhow!("Failed to run dwarfdump: {e}. Is Xcode installed?"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("dwarfdump failed: {stderr}");
    }

    let stdout = String::from_utf8_lossy(&output.stdout);

    // Parse output like: "UUID: 12345678-1234-1234-1234-123456789ABC (arm64) /path/to/file"
    // Universal binaries have multiple lines, one per architecture
    let uuids: Vec<String> = stdout
        .lines()
        .filter_map(|line| {
            line.find("UUID: ").and_then(|uuid_start| {
                let uuid_part = &line[uuid_start + 6..];
                uuid_part.find(' ').map(|uuid_end| {
                    // Uppercase for standard UUID format
                    uuid_part[..uuid_end].to_uppercase()
                })
            })
        })
        .collect();

    if uuids.is_empty() {
        anyhow::bail!(
            "Could not extract any UUIDs from dSYM at {}. dwarfdump output: {}",
            dsym_path.display(),
            stdout
        );
    }

    Ok(uuids)
}

/// Zip a dSYM bundle into memory
fn zip_dsym_bundle(dsym_path: &PathBuf) -> Result<Vec<u8>> {
    use std::fs::File;
    use std::io::Read;
    use std::io::{Cursor, Write};
    use walkdir::WalkDir;

    let mut buffer = Cursor::new(Vec::new());

    {
        let mut zip = zip::ZipWriter::new(&mut buffer);
        let options = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);

        for entry in WalkDir::new(dsym_path) {
            let entry = entry?;
            let path = entry.path();

            // Create relative path within the zip
            let relative_path = path.strip_prefix(dsym_path.parent().unwrap_or(dsym_path))?;
            let zip_path = relative_path.to_string_lossy();

            if path.is_file() {
                zip.start_file(zip_path.to_string(), options)?;
                let mut file = File::open(path)?;
                let mut contents = Vec::new();
                file.read_to_end(&mut contents)?;
                zip.write_all(&contents)?;
            } else if path.is_dir() && path != dsym_path.as_path() {
                // Add directory entry (but not the root)
                zip.add_directory(format!("{zip_path}/"), options)?;
            }
        }

        zip.finish()?;
    }

    Ok(buffer.into_inner())
}

/// Find all dSYM bundles in a directory
pub fn find_dsym_bundles(directory: &PathBuf) -> Result<Vec<PathBuf>> {
    use walkdir::WalkDir;

    let mut dsyms = Vec::new();

    for entry in WalkDir::new(directory).follow_links(true) {
        let entry = entry?;
        let path = entry.path();

        if path.is_dir() {
            if let Some(ext) = path.extension() {
                if ext == "dSYM" {
                    dsyms.push(path.to_path_buf());
                }
            }
        }
    }

    Ok(dsyms)
}

/// Info extracted from an Info.plist file
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct PlistInfo {
    /// CFBundleIdentifier (e.g., com.example.app)
    #[serde(rename = "CFBundleIdentifier")]
    pub bundle_identifier: Option<String>,
    /// CFBundleShortVersionString (e.g., 1.2.3)
    #[serde(rename = "CFBundleShortVersionString")]
    pub short_version: Option<String>,
    /// CFBundleVersion (e.g., 42)
    #[serde(rename = "CFBundleVersion")]
    pub bundle_version: Option<String>,
    /// CFBundleDevelopmentRegion (e.g., English, en)
    #[serde(rename = "CFBundleDevelopmentRegion")]
    pub development_region: Option<String>,
}

impl PlistInfo {
    /// Extract version info from an Info.plist file path
    pub fn from_plist(plist_path: &Path) -> Result<Self> {
        if !plist_path.exists() {
            anyhow::bail!("Info.plist not found at {}", plist_path.display());
        }

        let plist = plist::Value::from_file(plist_path)
            .map_err(|e| anyhow!("Failed to parse Info.plist: {e}"))?;

        let dict = plist
            .as_dictionary()
            .ok_or_else(|| anyhow!("Info.plist is not a dictionary"))?;

        Ok(Self {
            bundle_identifier: dict
                .get("CFBundleIdentifier")
                .and_then(|v| v.as_string())
                .map(|s| s.to_string()),
            short_version: dict
                .get("CFBundleShortVersionString")
                .and_then(|v| v.as_string())
                .map(|s| s.to_string()),
            bundle_version: dict
                .get("CFBundleVersion")
                .and_then(|v| v.as_string())
                .map(|s| s.to_string()),
            development_region: dict
                .get("CFBundleDevelopmentRegion")
                .and_then(|v| v.as_string())
                .map(|s| s.to_string()),
        })
    }
}
