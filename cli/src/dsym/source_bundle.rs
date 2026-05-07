use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::io::Cursor;
use std::path::Path;

use anyhow::Result;
use serde::{Deserialize, Serialize};
use symbolic::debuginfo::dwarf::{gimli, Dwarf as DwarfObject};
use symbolic::debuginfo::{Archive, Object};
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

/// Extract all source file paths referenced in a DWARF binary file.
///
/// ## Strategy: CU-anchored line-table walk
///
/// We need two properties that are in tension:
///
/// 1. **Completeness** — under Swift Whole-Module Optimisation (WMO), source
///    files like `SwiftCrashTriggers.swift` have *no own
///    `DW_TAG_compile_unit`*. They only appear as inlined callees inside
///    another file's CU.  A loop over CU root DIEs alone would miss them,
///    guaranteeing no source context for any of their inlined frames.
///
/// 2. **Hash stability** — `session.files()` (symbolic's full line-table walk)
///    also picks up files from *imported* frameworks referenced via
///    `DW_AT_decl_file` on type/variable declarations. When a first-party
///    dependency (e.g. `PostHog.framework`) is rebuilt with a new UUID, its
///    source files change on disk, causing the app's source-bundle ZIP to
///    differ even though the app's UUID is identical → `content_hash_mismatch`.
///
/// **Solution**: two-pass approach.
///
/// *Pass 1* — walk only `DW_TAG_compile_unit` root DIEs via gimli (no line
/// table). These CU main files are definitively "compiled into this binary".
/// From them we derive the **project root prefix** — the longest common
/// directory ancestor of all CU main files.
///
/// *Pass 2* — run `session.files()` (full line-table walk) but retain only
/// paths that share the project root prefix. This picks up inlined callees
/// (e.g. `SwiftCrashTriggers.swift`) that live inside the project tree but
/// have no own CU, while silently dropping all framework/SDK headers and
/// first-party dependency source files that live in a different directory tree.
pub fn extract_source_paths_from_dwarf(dwarf_path: &Path) -> Result<Vec<String>> {
    let dwarf_data = fs::read(dwarf_path)?;
    let archive = Archive::parse(&dwarf_data)?;

    let mut paths: HashSet<String> = HashSet::new();

    for obj in archive.objects() {
        let obj = obj?;

        // Pass 1: CU-only walk to derive the project root prefix.
        let cu_paths = collect_cu_main_files_gimli(&obj);
        let project_prefix = longest_common_prefix(&cu_paths);
        tracing::debug!(
            "CU main files: {:?}  →  project prefix: {:?}",
            cu_paths,
            project_prefix
        );

        // Pass 2: full line-table walk, filtered to the project prefix.
        let session = obj.debug_session()?;
        for file in session.files() {
            let file = file?;
            let abs_path = file.abs_path_str();
            if abs_path.is_empty() {
                continue;
            }
            // Only keep paths inside the project tree.
            // If we couldn't derive a prefix fall back to keeping everything
            // (the normal EXCLUDED_PREFIXES / EXCLUDED_SUBSTRINGS filters still apply).
            let in_project = match &project_prefix {
                Some(prefix) => abs_path.starts_with(prefix.as_str()),
                None => true,
            };
            if in_project {
                paths.insert(abs_path);
            } else {
                tracing::debug!("Skipped (outside project prefix): {}", abs_path);
            }
        }
    }

    let mut paths: Vec<String> = paths.into_iter().collect();
    paths.sort();

    for p in &paths {
        tracing::debug!("DWARF source path: {}", p);
    }

    Ok(paths)
}

/// Walk only `DW_TAG_compile_unit` root DIEs via gimli (no line table) and
/// return the resolved absolute path of the main file for each CU.
///
/// This deliberately does **not** read the line-number program, so cross-module
/// file references that appear there (e.g. type-declaration sites in imported
/// frameworks) are never included.
fn collect_cu_main_files_gimli(obj: &Object<'_>) -> Vec<String> {
    match obj {
        Object::MachO(m) => cu_main_files_from_dwarf(m),
        Object::Elf(e) => cu_main_files_from_dwarf(e),
        _ => Vec::new(),
    }
}

fn cu_main_files_from_dwarf<'d>(obj: &impl DwarfObject<'d>) -> Vec<String> {
    let empty: &[u8] = &[];

    let info_data = obj
        .section("debug_info")
        .map(|s| s.data.into_owned())
        .unwrap_or_default();
    let abbrev_data = obj
        .section("debug_abbrev")
        .map(|s| s.data.into_owned())
        .unwrap_or_default();
    let str_data = obj
        .section("debug_str")
        .map(|s| s.data.into_owned())
        .unwrap_or_default();
    let line_str_data = obj
        .section("debug_line_str")
        .map(|s| s.data.into_owned())
        .unwrap_or_default();

    let endian = if matches!(obj.endianity(), gimli::RunTimeEndian::Big) {
        gimli::RunTimeEndian::Big
    } else {
        gimli::RunTimeEndian::Little
    };

    let dwarf = gimli::Dwarf {
        debug_info: gimli::DebugInfo::new(&info_data, endian),
        debug_abbrev: gimli::DebugAbbrev::new(&abbrev_data, endian),
        debug_str: gimli::DebugStr::new(&str_data, endian),
        debug_line_str: gimli::DebugLineStr::new(&line_str_data, endian),
        // Sections not needed for CU-name extraction — leave empty.
        debug_addr: gimli::DebugAddr::from(gimli::EndianSlice::new(empty, endian)),
        debug_aranges: gimli::DebugAranges::new(empty, endian),
        debug_line: gimli::DebugLine::new(empty, endian),
        debug_str_offsets: gimli::DebugStrOffsets::from(gimli::EndianSlice::new(empty, endian)),
        debug_types: Default::default(),
        debug_macinfo: gimli::DebugMacinfo::new(empty, endian),
        debug_macro: gimli::DebugMacro::new(empty, endian),
        locations: Default::default(),
        ranges: gimli::RangeLists::new(
            gimli::DebugRanges::new(empty, endian),
            gimli::DebugRngLists::new(empty, endian),
        ),
        file_type: gimli::DwarfFileType::Main,
        abbreviations_cache: Default::default(),
        sup: None,
    };

    let resolve_str =
        |val: gimli::AttributeValue<gimli::EndianSlice<'_, gimli::RunTimeEndian>>| -> Option<String> {
            match val {
                gimli::AttributeValue::String(s) => {
                    std::str::from_utf8(s.slice()).ok().map(|s| s.to_string())
                }
                gimli::AttributeValue::DebugStrRef(offset) => dwarf
                    .debug_str
                    .get_str(offset)
                    .ok()
                    .and_then(|s| std::str::from_utf8(s.slice()).ok().map(|s| s.to_string())),
                gimli::AttributeValue::DebugLineStrRef(offset) => dwarf
                    .debug_line_str
                    .get_str(offset)
                    .ok()
                    .and_then(|s| std::str::from_utf8(s.slice()).ok().map(|s| s.to_string())),
                _ => None,
            }
        };

    let mut out = Vec::new();
    let mut iter = dwarf.units();
    loop {
        let header = match iter.next() {
            Ok(Some(h)) => h,
            Ok(None) => break,
            Err(e) => {
                tracing::debug!("DWARF units() error: {:?}", e);
                break;
            }
        };
        let abbrevs = match dwarf.abbreviations(&header) {
            Ok(a) => a,
            Err(_) => continue,
        };
        // Parse only the root DIE — do NOT call dwarf.unit() which also tries
        // to load the line program (which would fail with our empty debug_line).
        let mut cursor = header.entries(&abbrevs);
        let root = match cursor.next_dfs() {
            Ok(Some((_, e))) => e,
            _ => continue,
        };
        if root.tag() != gimli::DW_TAG_compile_unit {
            continue;
        }

        let comp_dir: Option<String> = root
            .attr_value(gimli::DW_AT_comp_dir)
            .ok()
            .flatten()
            .and_then(&resolve_str);
        let name: Option<String> = root
            .attr_value(gimli::DW_AT_name)
            .ok()
            .flatten()
            .and_then(&resolve_str);

        let path = match (comp_dir, name) {
            // Swift emits synthetic CUs with `DW_AT_name = "<swift-imported-modules>"`
            // alongside a real `DW_AT_comp_dir`. Without this guard the join below
            // produces e.g. `/…/Project.xcodeproj/<swift-imported-modules>`, which
            // escapes the `EXCLUDED_SYNTHETIC_NAMES` `starts_with` check further down
            // and ends up dominating the project-root prefix computation — causing
            // every real source file to be rejected as "outside project prefix".
            (_, Some(name)) if name.starts_with('<') => continue,
            (Some(dir), Some(name)) if !name.starts_with('/') => {
                format!("{}/{}", dir.trim_end_matches('/'), name)
            }
            (_, Some(name)) if name.starts_with('/') => name,
            (Some(dir), None) => dir,
            _ => continue,
        };

        if !path.is_empty() {
            out.push(path);
        }
    }
    // Drop synthetic linker-generated names and system/DerivedData paths before
    // returning so they never poison the project-root prefix computation.
    out.retain(|p| {
        if EXCLUDED_SYNTHETIC_NAMES.iter().any(|s| p.starts_with(s)) {
            return false;
        }
        if EXCLUDED_PREFIXES.iter().any(|s| p.starts_with(s)) {
            return false;
        }
        if EXCLUDED_SUBSTRINGS.iter().any(|s| p.contains(s)) {
            return false;
        }
        true
    });
    out
}

/// Return the longest common directory prefix shared by all `paths`.
///
/// Only directory components are considered (the filename is stripped before
/// comparison) so that two files in the same directory always share the full
/// directory path rather than only their common filename prefix.
///
/// Returns `None` if `paths` is empty.
fn longest_common_prefix(paths: &[String]) -> Option<String> {
    if paths.is_empty() {
        return None;
    }

    // Work with directory paths only.
    let dirs: Vec<&str> = paths
        .iter()
        .map(|p| {
            // Find last '/' and take everything up to and including it.
            if let Some(pos) = p.rfind('/') {
                &p[..=pos]
            } else {
                "/"
            }
        })
        .collect();

    let first = dirs[0];
    let mut prefix_len = first.len();
    for dir in &dirs[1..] {
        // Use char_indices so byte_pos is a valid byte offset (not a char count).
        let byte_pos = first
            .char_indices()
            .zip(dir.chars())
            .take_while(|((_, a), b)| a == b)
            .last()
            .map(|((pos, c), _)| pos + c.len_utf8())
            .unwrap_or(0);
        // Snap back to a '/' boundary, then take the minimum across all dirs.
        let new_len = first[..byte_pos].rfind('/').map(|p| p + 1).unwrap_or(0);
        prefix_len = prefix_len.min(new_len);
    }

    if prefix_len == 0 {
        None
    } else {
        Some(first[..prefix_len].to_string())
    }
}

/// Short root-level synthetic paths that Apple's Clang/Swift linker emits as
/// placeholder `DW_TAG_compile_unit` names for system frameworks. These are not
/// real file paths, cannot be read from disk, and must not contribute to the
/// project-root prefix computation (they would drag it down to "/").
const EXCLUDED_SYNTHETIC_NAMES: &[&str] = &[
    "/_AvailabilityInternal",
    "/_Builtin_",
    "/_DarwinFoundation",
    "/CFNetwork",
    "/CoreFoundation",
    "/Darwin",
    "/Dispatch",
    "/Foundation",
    "/MachO",
    "/ObjectiveC",
    "/Security",
    "/XPC",
    "/asl",
    "/os_",
    "/ptrcheck",
    "/ptrauth",
    "<stdin>",
    "<swift-imported-modules>",
];

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

/// Filter out system framework, SDK, and synthetic linker paths, keeping only user source files.
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
            // Exclude synthetic compiler/linker placeholder names
            if EXCLUDED_SYNTHETIC_NAMES.iter().any(|s| path.starts_with(s)) {
                tracing::debug!("Filtered out (synthetic): {}", path);
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
