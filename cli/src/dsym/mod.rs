use std::path::PathBuf;

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
    /// The UUID of the dSYM (used as chunk_id for matching)
    pub uuid: String,
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

        // Extract UUID from the dSYM
        let uuid = extract_dsym_uuid(path)?;

        // Zip the dSYM bundle
        let data = zip_dsym_bundle(path)?;

        Ok(Self {
            uuid,
            data,
            release_id: None,
        })
    }
}

impl TryInto<SymbolSetUpload> for DsymFile {
    type Error = anyhow::Error;

    fn try_into(self) -> Result<SymbolSetUpload> {
        Ok(SymbolSetUpload {
            chunk_id: self.uuid,
            release_id: self.release_id,
            data: self.data,
        })
    }
}

/// Extract the UUID from a dSYM bundle using dwarfdump
fn extract_dsym_uuid(dsym_path: &PathBuf) -> Result<String> {
    use std::process::Command;

    let output = Command::new("dwarfdump")
        .arg("--uuid")
        .arg(dsym_path)
        .output()
        .map_err(|e| anyhow!("Failed to run dwarfdump: {}. Is Xcode installed?", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("dwarfdump failed: {}", stderr);
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    
    // Parse output like: "UUID: 12345678-1234-1234-1234-123456789ABC (arm64) /path/to/file"
    // There may be multiple UUIDs for universal binaries, we take the first one
    for line in stdout.lines() {
        if let Some(uuid_start) = line.find("UUID: ") {
            let uuid_part = &line[uuid_start + 6..];
            if let Some(uuid_end) = uuid_part.find(' ') {
                let uuid = &uuid_part[..uuid_end];
                // Uppercase for standard UUID format
                return Ok(uuid.to_uppercase());
            }
        }
    }

    anyhow::bail!(
        "Could not extract UUID from dSYM at {}. dwarfdump output: {}",
        dsym_path.display(),
        stdout
    )
}

/// Zip a dSYM bundle into memory
fn zip_dsym_bundle(dsym_path: &PathBuf) -> Result<Vec<u8>> {
    use std::io::{Cursor, Write};
    use std::fs::File;
    use std::io::Read;
    use walkdir::WalkDir;

    let mut buffer = Cursor::new(Vec::new());
    
    {
        let mut zip = zip::ZipWriter::new(&mut buffer);
        let options = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);

        let _dsym_name = dsym_path
            .file_name()
            .ok_or_else(|| anyhow!("Invalid dSYM path"))?
            .to_string_lossy();

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
                zip.add_directory(format!("{}/", zip_path), options)?;
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

/// Info extracted from a dSYM's Info.plist
#[derive(Debug, Clone, Default)]
pub struct PlistInfo {
    /// CFBundleIdentifier (e.g., com.example.app)
    pub bundle_identifier: Option<String>,
    /// CFBundleShortVersionString (e.g., 1.2.3)
    pub short_version: Option<String>,
    /// CFBundleVersion (e.g., 42)
    pub bundle_version: Option<String>,
}

/// Extract version info from a dSYM bundle's Info.plist
pub fn extract_plist_info(dsym_path: &PathBuf) -> Result<PlistInfo> {
    let plist_path = dsym_path.join("Contents/Info.plist");

    if !plist_path.exists() {
        anyhow::bail!("Info.plist not found at {}", plist_path.display());
    }

    let plist = plist::Value::from_file(&plist_path)
        .map_err(|e| anyhow!("Failed to parse Info.plist: {}", e))?;

    let dict = plist
        .as_dictionary()
        .ok_or_else(|| anyhow!("Info.plist is not a dictionary"))?;

    Ok(PlistInfo {
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
    })
}
