use std::path::{Path, PathBuf};

use crate::api::symbol_sets::SymbolSetUpload;
use anyhow::{anyhow, Result};
use clap::Subcommand;
use posthog_symbol_data::{write_symbol_data, AppleDsym};

pub mod source_bundle;
pub mod upload;

#[derive(Subcommand)]
pub enum DsymSubcommand {
    /// Upload iOS/macOS dSYM files
    Upload(upload::Args),
}

/// A single DWARF binary extracted from a dSYM bundle, ready for upload
struct DsymEntry {
    /// The UUID of this DWARF binary (used as chunk_id)
    uuid: String,
    /// ZIP containing only this DWARF binary (+ optional source files)
    data: Vec<u8>,
}

/// Represents a dSYM bundle ready for upload.
/// Each DWARF binary in the bundle gets its own ZIP, keyed by its UUID.
pub struct DsymFile {
    entries: Vec<DsymEntry>,
    /// Optional release ID
    pub release_id: Option<String>,
}

impl DsymFile {
    /// Create a new DsymFile from a .dSYM bundle path.
    /// Each DWARF binary in the bundle gets its own ZIP so that
    /// stable UUIDs (e.g. app stubs) don't get a new content hash
    /// when a sibling binary (e.g. debug dylib) changes.
    pub fn new(path: &PathBuf, include_source: bool) -> Result<Self> {
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

        let dwarf_dir = path.join("Contents/Resources/DWARF");
        let uuid_entries = extract_dsym_uuids(path)?;

        let mut entries = Vec::new();
        for (uuid, dwarf_filename) in &uuid_entries {
            let dwarf_path = dwarf_dir.join(dwarf_filename);
            let data = zip_dwarf_binary(&dwarf_path, include_source)?;
            entries.push(DsymEntry {
                uuid: uuid.clone(),
                data,
            });
        }

        Ok(Self {
            entries,
            release_id: None,
        })
    }

    pub fn uuids(&self) -> Vec<&str> {
        self.entries.iter().map(|e| e.uuid.as_str()).collect()
    }

    pub fn total_size(&self) -> usize {
        self.entries.iter().map(|e| e.data.len()).sum()
    }

    /// Convert to SymbolSetUploads (one per UUID)
    pub fn into_uploads(self) -> Vec<SymbolSetUpload> {
        self.entries
            .into_iter()
            .map(|entry| SymbolSetUpload {
                chunk_id: entry.uuid,
                release_id: self.release_id.clone(),
                data: entry.data,
            })
            .collect()
    }
}

/// Extract all UUIDs and their corresponding DWARF filenames from a dSYM bundle.
/// Returns (uuid, dwarf_filename) pairs.
fn extract_dsym_uuids(dsym_path: &PathBuf) -> Result<Vec<(String, String)>> {
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

    // Parse output like: "UUID: 12345678-1234-1234-1234-123456789ABC (arm64) /path/to/DWARF/PostHogExample"
    let entries: Vec<(String, String)> = stdout
        .lines()
        .filter_map(|line| {
            let uuid_start = line.find("UUID: ")? + 6;
            let uuid_part = &line[uuid_start..];
            let uuid_end = uuid_part.find(' ')?;
            let uuid = uuid_part[..uuid_end].to_uppercase();

            // Extract the DWARF filename from the path at end of line
            // Format: "UUID: <uuid> (<arch>) <full_path>"
            let path_start = line.rfind(')')? + 2; // Skip ") "
            let dwarf_path = line.get(path_start..)?;
            let dwarf_filename = Path::new(dwarf_path).file_name()?.to_str()?.to_string();

            Some((uuid, dwarf_filename))
        })
        .collect();

    if entries.is_empty() {
        anyhow::bail!(
            "Could not extract any UUIDs from dSYM at {}. dwarfdump output: {}",
            dsym_path.display(),
            stdout
        );
    }

    Ok(entries)
}

/// Create a minimal ZIP containing a single DWARF binary and optional source files.
/// The ZIP layout is:
///   dwarf                    — the raw DWARF Mach-O binary
///   __source/manifest.json   — (optional) source file manifest
///   __source/...             — (optional) source files
fn zip_dwarf_binary(dwarf_path: &Path, include_source: bool) -> Result<Vec<u8>> {
    use std::fs::File;
    use std::io::Read;
    use std::io::{Cursor, Write};
    use tracing::info;

    let mut buffer = Cursor::new(Vec::new());

    {
        let mut zip = zip::ZipWriter::new(&mut buffer);
        let options = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);

        // Add the DWARF binary as "dwarf"
        zip.start_file("dwarf", options)?;
        let mut file = File::open(dwarf_path)?;
        let mut contents = Vec::new();
        file.read_to_end(&mut contents)?;
        zip.write_all(&contents)?;

        // Optionally include source files referenced by this DWARF binary
        if include_source {
            match source_bundle::extract_source_paths_from_dwarf(dwarf_path) {
                Ok(all_paths) => {
                    let filtered = source_bundle::filter_source_paths(&all_paths);
                    info!(
                        "Found {} source paths in DWARF ({} after filtering)",
                        all_paths.len(),
                        filtered.len()
                    );

                    if !filtered.is_empty() {
                        match source_bundle::collect_source_files(&filtered) {
                            Ok(source_files) => {
                                source_bundle::add_source_to_zip(&mut zip, &source_files)?;
                            }
                            Err(e) => {
                                tracing::warn!("Failed to collect source files: {} (continuing without source)", e);
                            }
                        }
                    }
                }
                Err(e) => {
                    tracing::warn!(
                        "Failed to extract DWARF source paths: {} (continuing without source)",
                        e
                    );
                }
            }
        }

        zip.finish()?;
    }

    let zip_data = buffer.into_inner();
    let wrapped = write_symbol_data(AppleDsym { data: zip_data })?;
    Ok(wrapped)
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
