use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::io::Cursor;
use std::path::Path;

use anyhow::Result;
use serde::{Deserialize, Serialize};
use symbolic::debuginfo::Archive;
use tracing::{info, warn};

/// Manifest format stored as `__source/manifest.json` inside the dSYM ZIP
#[derive(Serialize, Deserialize)]
pub struct SourceManifest {
    pub version: u32,
    /// Maps absolute DWARF source path → ZIP-relative path (e.g. "__source/Foo.swift")
    pub files: BTreeMap<String, String>,
}

/// Collected source files ready to be added to a ZIP
pub struct SourceFiles {
    pub manifest: SourceManifest,
    /// Maps ZIP-relative path → file content (BTreeMap for deterministic zip ordering)
    pub contents: BTreeMap<String, Vec<u8>>,
}

/// Extract all source file paths referenced in DWARF debug info from a dSYM bundle.
///
/// Finds the DWARF binary at `<dSYM>/Contents/Resources/DWARF/<name>`,
/// parses it with `symbolic`, and collects all referenced source file paths.
pub fn extract_dwarf_source_paths(dsym_path: &Path) -> Result<Vec<String>> {
    let dwarf_dir = dsym_path.join("Contents/Resources/DWARF");

    if !dwarf_dir.is_dir() {
        anyhow::bail!("DWARF directory not found at {}", dwarf_dir.display());
    }

    // Find the DWARF binary (there's typically one file in this directory)
    let dwarf_binary = fs::read_dir(&dwarf_dir)?
        .filter_map(|e| e.ok())
        .find(|e| e.path().is_file())
        .ok_or_else(|| anyhow::anyhow!("No DWARF binary found in {}", dwarf_dir.display()))?;

    let dwarf_data = fs::read(dwarf_binary.path())?;
    let archive = Archive::parse(&dwarf_data)?;

    let mut paths = Vec::new();

    for obj in archive.objects() {
        let obj = obj?;
        let session = obj.debug_session()?;
        for file in session.files() {
            let file = file?;
            let abs_path = file.abs_path_str();
            if !abs_path.is_empty() {
                paths.push(abs_path);
            }
        }
    }

    // Deduplicate
    paths.sort();
    paths.dedup();

    for p in &paths {
        tracing::debug!("DWARF source path: {}", p);
    }

    Ok(paths)
}

/// System/SDK path prefixes to exclude from source bundling
const EXCLUDED_PREFIXES: &[&str] = &[
    "/usr/",
    "/Library/Developer/",
    "/Applications/Xcode",
    "/System/",
];

/// Path substrings that indicate system/generated code
const EXCLUDED_SUBSTRINGS: &[&str] = &[
    "/Xcode.app/",
    "/SDKs/",
    "<compiler-generated>",
    "<built-in>",
    "/DerivedData/",
];

/// Filter out system framework and SDK paths, keeping only user source files.
pub fn filter_source_paths(paths: &[String]) -> Vec<&str> {
    paths
        .iter()
        .filter(|path| {
            // Exclude system prefixes
            if EXCLUDED_PREFIXES
                .iter()
                .any(|prefix| path.starts_with(prefix))
            {
                tracing::debug!("Filtered out (prefix): {}", path);
                return false;
            }
            // Exclude paths containing system substrings
            if EXCLUDED_SUBSTRINGS.iter().any(|sub| path.contains(sub)) {
                tracing::debug!("Filtered out (substring): {}", path);
                return false;
            }
            true
        })
        .map(|s| s.as_str())
        .collect()
}

/// Collect source files from disk, reading each file referenced by DWARF debug info.
///
/// Since the CLI runs on the build machine, the absolute paths from DWARF are valid.
/// Files that don't exist are skipped with a warning.
pub fn collect_source_files(dwarf_paths: &[&str]) -> Result<SourceFiles> {
    let mut manifest_files = BTreeMap::new();
    let mut contents = BTreeMap::new();

    // Build a disambiguated relative path for each source file.
    // We use a simple approach: strip common prefix to get a short relative path,
    // and if there are collisions, use increasingly longer path components.
    let zip_paths = build_zip_relative_paths(dwarf_paths);

    for (dwarf_path, zip_rel_path) in dwarf_paths.iter().zip(zip_paths.iter()) {
        let path = Path::new(dwarf_path);
        match fs::read(path) {
            Ok(data) => {
                let zip_path = format!("__source/{}", zip_rel_path);
                manifest_files.insert(dwarf_path.to_string(), zip_path.clone());
                contents.insert(zip_path, data);
            }
            Err(e) => {
                warn!(
                    "Could not read source file {}: {} (skipping)",
                    dwarf_path, e
                );
            }
        }
    }

    for (dwarf_path, zip_path) in &manifest_files {
        tracing::debug!("Manifest entry: {} -> {}", dwarf_path, zip_path);
    }

    info!(
        "Collected {} source files ({} bytes total)",
        contents.len(),
        contents.values().map(|v| v.len()).sum::<usize>()
    );

    Ok(SourceFiles {
        manifest: SourceManifest {
            version: 1,
            files: manifest_files,
        },
        contents,
    })
}

/// Add source files to an existing ZIP writer.
///
/// Writes `__source/manifest.json` and all source file contents under `__source/`.
pub fn add_source_to_zip<W: std::io::Write + std::io::Seek>(
    zip: &mut zip::ZipWriter<W>,
    source_files: &SourceFiles,
) -> Result<()> {
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    // Write manifest
    let manifest_json = serde_json::to_vec_pretty(&source_files.manifest)?;
    zip.start_file("__source/manifest.json", options)?;
    std::io::Write::write_all(zip, &manifest_json)?;

    // Write source files
    for (zip_path, data) in &source_files.contents {
        zip.start_file(zip_path.clone(), options)?;
        std::io::Write::write_all(zip, data)?;
    }

    Ok(())
}

/// Build disambiguated relative paths for ZIP storage.
///
/// For a set of absolute paths, this creates short relative paths that are unique.
/// If two files have the same filename, it includes parent directory components
/// until they're disambiguated.
fn build_zip_relative_paths(paths: &[&str]) -> Vec<String> {
    // Start with just the filename
    let mut result: Vec<String> = paths
        .iter()
        .map(|p| {
            Path::new(p)
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("unknown")
                .to_string()
        })
        .collect();

    // Find and resolve duplicates by adding parent components
    let max_iterations = 10; // Safety limit
    for _ in 0..max_iterations {
        let mut seen: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, name) in result.iter().enumerate() {
            seen.entry(name.clone()).or_default().push(i);
        }

        let mut has_duplicates = false;
        for indices in seen.values() {
            if indices.len() > 1 {
                has_duplicates = true;
                for &idx in indices {
                    // Add one more parent component
                    let components: Vec<&str> =
                        paths[idx].split('/').filter(|s| !s.is_empty()).collect();
                    let current_depth = result[idx].matches('/').count() + 1;
                    let new_depth = (current_depth + 1).min(components.len());
                    let start = components.len().saturating_sub(new_depth);
                    result[idx] = components[start..].join("/");
                }
            }
        }

        if !has_duplicates {
            break;
        }
    }

    result
}

/// Read source from a dSYM ZIP that was loaded into memory.
/// Used by Cymbal to extract source files from the uploaded bundle.
pub fn read_source_manifest_from_zip(
    archive: &mut zip::ZipArchive<Cursor<Vec<u8>>>,
) -> Option<SourceManifest> {
    let mut manifest_file = archive.by_name("__source/manifest.json").ok()?;
    let mut manifest_data = Vec::new();
    std::io::Read::read_to_end(&mut manifest_file, &mut manifest_data).ok()?;
    serde_json::from_slice(&manifest_data).ok()
}

/// Load all source file contents from a dSYM ZIP using the manifest.
pub fn load_sources_from_zip(
    archive: &mut zip::ZipArchive<Cursor<Vec<u8>>>,
    manifest: &SourceManifest,
) -> HashMap<String, String> {
    let mut sources = HashMap::new();

    for (dwarf_path, zip_path) in &manifest.files {
        if let Ok(mut file) = archive.by_name(zip_path) {
            let mut content = String::new();
            if std::io::Read::read_to_string(&mut file, &mut content).is_ok() {
                sources.insert(dwarf_path.clone(), content);
            }
        }
    }

    sources
}
