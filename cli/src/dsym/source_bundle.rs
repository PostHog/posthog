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
    extract_source_paths_from_dwarf_bytes(&dwarf_data)
}

/// Like [`extract_source_paths_from_dwarf`], but for callers that already
/// hold the binary in memory, avoiding a second read from disk.
pub fn extract_source_paths_from_dwarf_bytes(dwarf_data: &[u8]) -> Result<Vec<String>> {
    let archive = Archive::parse(dwarf_data)?;

    let mut paths: HashSet<String> = HashSet::new();

    let mut any_go = false;
    for obj in archive.objects() {
        let obj = obj?;

        // Pass 1: CU-only walk to derive the project root prefix. Go CUs are
        // packages, not files: DW_AT_name is the package import path
        // ("internal/godebug") and DW_AT_comp_dir is "." — they contribute
        // nothing to the prefix (which cgo C/C++ CUs, when present, still
        // provide). For Go the line table is the source of truth instead:
        // on-disk (absolute) `.go`/`.s` paths are kept, and Go toolchain
        // sources are trimmed after the walk. `-trimpath` builds record no
        // absolute paths at all, so they yield nothing here by design.
        let cu_info = collect_cu_main_files_gimli(&obj);
        any_go |= cu_info.has_go;
        let project_prefix = longest_common_prefix(&cu_info.main_files);
        tracing::debug!(
            "CU main files: {:?} (go: {})  →  project prefix: {:?}",
            cu_info.main_files,
            cu_info.has_go,
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
            // Only keep paths inside the project tree, plus — for Go — files
            // that pass the Go source gate (pure Go binaries derive no prefix;
            // cgo binaries need the union to keep both languages' sources).
            // If we couldn't derive a prefix fall back to keeping everything
            // (the normal EXCLUDED_PREFIXES / EXCLUDED_SUBSTRINGS filters still apply).
            let in_project = match &project_prefix {
                Some(prefix) => {
                    abs_path.starts_with(prefix.as_str())
                        || (cu_info.has_go && is_bundleable_go_source(&abs_path))
                }
                None if cu_info.has_go => is_bundleable_go_source(&abs_path),
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
    if any_go {
        paths = filter_go_toolchain_sources(paths);
    }

    for p in &paths {
        tracing::debug!("DWARF source path: {}", p);
    }

    Ok(paths)
}

/// Whether a Go line-table path may be read from disk and bundled. Requires
/// an absolute path (Unix, or drive-qualified for ELFs built on Windows) and
/// a Go source extension: line-table entries are attacker-influenced —
/// `//line` directives in any dependency name arbitrary files — so this keeps
/// the reachable set to source files rather than, say, `/etc/passwd`.
fn is_bundleable_go_source(path: &str) -> bool {
    let absolute = path.starts_with('/')
        || (path.len() > 2
            && path.as_bytes()[0].is_ascii_alphabetic()
            && path.as_bytes()[1] == b':'
            && matches!(path.as_bytes()[2], b'/' | b'\\'));
    // Compiler-normalized paths never contain dot components; a spoofed one
    // could otherwise smuggle `..` into derived ZIP entry names (zip slip).
    let normalized = !path
        .split(['/', '\\'])
        .any(|component| component == "." || component == "..");
    absolute && normalized && (path.ends_with(".go") || path.ends_with(".s"))
}

/// Drop Go toolchain sources, keeping project code. Runs for any binary with
/// Go CUs, on whichever upload path (ELF or dSYM) extracted the paths.
///
/// GOROOT gives no fixed marker to filter on — it lands wherever the
/// toolchain was installed (/usr/local/go, homebrew Cellar, nix store). Every
/// Go binary unconditionally compiles in the runtime package though, so a
/// directory whose `src/runtime/` holds several of its always-present files
/// is a GOROOT src root; everything under it is stdlib. Requiring multiple
/// witness files keeps a project that merely contains a `src/runtime/`
/// directory (or a single spoofed `//line` entry) from marking its own tree
/// as stdlib — misdetection would only suppress source context, never leak
/// anything. Matching happens on /-normalized copies so ELFs built on
/// Windows (backslash-separated DWARF paths) hit the same filters.
fn filter_go_toolchain_sources(paths: Vec<String>) -> Vec<String> {
    const GOROOT_WITNESSES: &[&str] = &[
        "runtime/proc.go",
        "runtime/malloc.go",
        "runtime/mgc.go",
        "runtime/runtime2.go",
    ];
    let normalize = |p: &str| p.replace('\\', "/");
    let normalized_set: HashSet<String> = paths.iter().map(|p| normalize(p)).collect();
    let goroot_src_roots: Vec<String> = normalized_set
        .iter()
        .filter_map(|p| {
            p.find("/src/runtime/proc.go")
                .map(|i| p[..i + "/src/".len()].to_string())
        })
        .filter(|root| {
            GOROOT_WITNESSES
                .iter()
                .all(|w| normalized_set.contains(&format!("{root}{w}")))
        })
        .collect();

    paths
        .into_iter()
        .filter(|path| {
            let normalized = normalize(path);
            // The module cache holds dependency sources, not project code.
            if normalized.contains("/pkg/mod/") {
                tracing::debug!("Filtered out (Go module cache): {}", path);
                return false;
            }
            if goroot_src_roots
                .iter()
                .any(|root| normalized.starts_with(root.as_str()))
            {
                tracing::debug!("Filtered out (Go stdlib): {}", path);
                return false;
            }
            true
        })
        .collect()
}

/// CU-level facts gathered without reading any line program.
#[derive(Default)]
struct CuInfo {
    /// Resolved absolute paths of each CU's main file (non-Go CUs only).
    main_files: Vec<String>,
    /// Whether any CU is Go (`DW_AT_language == DW_LANG_Go`).
    has_go: bool,
}

/// Walk only `DW_TAG_compile_unit` root DIEs via gimli (no line table) and
/// return the resolved absolute path of the main file for each CU.
///
/// This deliberately does **not** read the line-number program, so cross-module
/// file references that appear there (e.g. type-declaration sites in imported
/// frameworks) are never included.
fn collect_cu_main_files_gimli(obj: &Object<'_>) -> CuInfo {
    match obj {
        Object::MachO(m) => cu_main_files_from_dwarf(m),
        Object::Elf(e) => cu_main_files_from_dwarf(e),
        _ => CuInfo::default(),
    }
}

fn cu_main_files_from_dwarf<'d>(obj: &impl DwarfObject<'d>) -> CuInfo {
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

    let mut out = CuInfo::default();
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

        // Go CU names are package import paths, not source files — record the
        // language and skip them so they never poison the project prefix.
        if matches!(
            root.attr_value(gimli::DW_AT_language),
            Ok(Some(gimli::AttributeValue::Language(gimli::DW_LANG_Go)))
        ) {
            out.has_go = true;
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
            out.main_files.push(path);
        }
    }
    // Drop synthetic linker-generated names and system/DerivedData paths before
    // returning so they never poison the project-root prefix computation.
    out.main_files.retain(|p| {
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

/// Read one DWARF-named source file. Such paths are only expected to be
/// source files, but a hostile or corrupt entry can point anywhere, so:
/// symlinks are refused (a compiler records the file it read, not a link —
/// and a link named `legit.go` could target a credential file), the checks
/// run against the opened handle's metadata so the file can't be swapped
/// between check and read, non-regular files (devices, FIFOs) are refused,
/// and reads are capped generously enough that even large generated sources
/// (protobuf output, amalgamated C) are never clipped.
fn read_source_file(path: &Path) -> std::io::Result<Vec<u8>> {
    use std::io::{Error, ErrorKind, Read};

    const MAX_SOURCE_FILE_BYTES: u64 = 64 * 1024 * 1024;

    let err = |msg: &str| Err(Error::new(ErrorKind::InvalidInput, msg));
    if fs::symlink_metadata(path)?.file_type().is_symlink() {
        return err("path is a symlink");
    }
    let file = open_no_follow(path)?;
    let meta = file.metadata()?;
    if !meta.is_file() {
        return err("not a regular file");
    }
    if meta.len() > MAX_SOURCE_FILE_BYTES {
        return err("exceeds the source file size limit");
    }

    // Read one byte past the cap so a file that grew after the metadata
    // check errors out rather than being silently truncated in the bundle.
    let mut data = Vec::with_capacity(meta.len() as usize);
    file.take(MAX_SOURCE_FILE_BYTES + 1)
        .read_to_end(&mut data)?;
    if data.len() as u64 > MAX_SOURCE_FILE_BYTES {
        return err("exceeds the source file size limit");
    }
    Ok(data)
}

/// Open without following a symlink at the final component, so the symlink
/// check above can't be raced by swapping the path between check and open.
#[cfg(unix)]
fn open_no_follow(path: &Path) -> std::io::Result<fs::File> {
    use std::os::unix::fs::OpenOptionsExt;
    fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
}

/// Windows has no O_NOFOLLOW equivalent in std; creating symlinks there
/// requires elevated privileges, so the metadata pre-check has to do.
#[cfg(not(unix))]
fn open_no_follow(path: &Path) -> std::io::Result<fs::File> {
    fs::File::open(path)
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
            // Exclude system prefixes. Go sources are exempt: containerized
            // Go builds commonly live under /usr/src (the official golang
            // image's WORKDIR), and Go's own system trees — GOROOT wherever
            // installed and the module cache — are already handled by
            // filter_go_toolchain_sources.
            let is_go_source = path.ends_with(".go") || path.ends_with(".s");
            if !is_go_source
                && EXCLUDED_PREFIXES
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
        match read_source_file(Path::new(dwarf_path)) {
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
                    // Add one more parent component. Dot components are
                    // dropped: they never disambiguate, and a literal `..`
                    // would end up verbatim in a ZIP entry name, letting a
                    // crafted DWARF path escape the __source/ prefix on
                    // extraction (zip slip).
                    let components: Vec<&str> = paths[idx]
                        .split('/')
                        .filter(|s| !s.is_empty() && *s != "." && *s != "..")
                        .collect();
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

#[cfg(test)]
mod tests {
    use super::{
        build_zip_relative_paths, filter_go_toolchain_sources, is_bundleable_go_source,
        read_source_file,
    };

    #[test]
    fn go_line_table_paths_are_gated_to_absolute_source_files() {
        // On-disk source files, unix and drive-qualified.
        assert!(is_bundleable_go_source("/home/u/app/main.go"));
        assert!(is_bundleable_go_source("/home/u/app/asm_amd64.s"));
        assert!(is_bundleable_go_source("C:/workspace/app/main.go"));
        assert!(is_bundleable_go_source(r"C:\workspace\app\main.go"));

        // Relative and synthetic entries can't be read from disk.
        assert!(!is_bundleable_go_source("sync/once.go"));
        assert!(!is_bundleable_go_source("<autogenerated>"));
        assert!(!is_bundleable_go_source("?"));

        // `//line` directives name arbitrary files; only source is bundleable.
        assert!(!is_bundleable_go_source("/etc/passwd"));
        assert!(!is_bundleable_go_source("/home/u/.ssh/id_rsa"));

        // Dot components never appear in compiler-normalized paths and could
        // smuggle `..` into ZIP entry names.
        assert!(!is_bundleable_go_source("/a/../conflict.go"));
        assert!(!is_bundleable_go_source("/a/./conflict.go"));
        assert!(!is_bundleable_go_source(r"C:\a\..\conflict.go"));
    }

    #[test]
    fn zip_entry_names_never_contain_dot_components() {
        // Two same-basename paths force the collision loop to pull parent
        // components into the entry name; a literal `..` there would escape
        // the __source/ prefix on extraction.
        let paths = ["/a/../conflict.go", "/a/b/conflict.go"];
        for name in build_zip_relative_paths(&paths) {
            assert!(
                name.split('/')
                    .all(|c| c != ".." && c != "." && !c.is_empty()),
                "zip entry name {name:?} contains a traversal component"
            );
        }
    }

    #[test]
    fn symlinked_source_files_are_refused() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("secret");
        std::fs::write(&target, "sensitive").unwrap();
        let link = dir.path().join("legit.go");
        #[cfg(unix)]
        std::os::unix::fs::symlink(&target, &link).unwrap();
        #[cfg(windows)]
        std::os::windows::fs::symlink_file(&target, &link).unwrap();

        assert!(read_source_file(&link).is_err());
        assert_eq!(read_source_file(&target).unwrap(), b"sensitive");
    }

    fn goroot_witnesses(root: &str, sep: char) -> Vec<String> {
        ["proc.go", "malloc.go", "mgc.go", "runtime2.go"]
            .iter()
            .map(|f| format!("{root}{sep}src{sep}runtime{sep}{f}"))
            .collect()
    }

    #[test]
    fn go_toolchain_sources_are_filtered_out() {
        // GOROOT is recognized by its always-compiled runtime files,
        // wherever installed.
        let mut paths = goroot_witnesses("/nix/store/abc-go-1.25.5/share/go", '/');
        paths.extend(goroot_witnesses(
            "/opt/homebrew/Cellar/go/1.25.5/libexec",
            '/',
        ));
        paths.extend(
            [
                "/home/u/app/main.go",
                "/nix/store/abc-go-1.25.5/share/go/src/fmt/print.go",
                "/opt/homebrew/Cellar/go/1.25.5/libexec/src/net/http/server.go",
                // Module cache holds dependency sources, not project code.
                "/home/u/go/pkg/mod/github.com/posthog/posthog-go@v1.20.0/error_tracking.go",
            ]
            .into_iter()
            .map(String::from),
        );

        assert_eq!(
            filter_go_toolchain_sources(paths),
            vec!["/home/u/app/main.go"]
        );
    }

    #[test]
    fn windows_built_binaries_hit_the_same_go_filters() {
        let mut paths = goroot_witnesses(r"C:\go", '\\');
        paths.extend(
            [
                r"C:\workspace\app\main.go",
                r"C:\go\src\fmt\print.go",
                r"C:\Users\u\go\pkg\mod\github.com\dep@v1.0.0\dep.go",
            ]
            .into_iter()
            .map(String::from),
        );

        assert_eq!(
            filter_go_toolchain_sources(paths),
            vec![r"C:\workspace\app\main.go"]
        );
    }

    #[test]
    fn go_sources_under_usr_survive_the_system_prefix_filter() {
        // The official golang Docker image builds under /usr/src/app; the
        // /usr/ system-prefix rule must not empty those projects' bundles.
        let paths: Vec<String> = [
            "/usr/src/app/main.go",
            "/usr/src/app/asm_amd64.s",
            "/usr/include/stdio.h",
        ]
        .into_iter()
        .map(String::from)
        .collect();

        assert_eq!(
            super::filter_source_paths(&paths),
            vec!["/usr/src/app/main.go", "/usr/src/app/asm_amd64.s"]
        );
    }

    #[test]
    fn projects_under_a_src_runtime_path_keep_their_sources() {
        // A lone src/runtime/proc.go (project layout collision, or a spoofed
        // //line entry) is not enough evidence of a GOROOT — all runtime
        // witness files must be present.
        let paths: Vec<String> = [
            "/work/src/runtime/proc.go",
            "/work/src/runtime/app/main.go",
            "/work/src/api/server.go",
        ]
        .into_iter()
        .map(String::from)
        .collect();

        assert_eq!(filter_go_toolchain_sources(paths.clone()), paths);
    }
}
