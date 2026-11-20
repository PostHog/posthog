// `--include-source`: the source files a binary's DWARF names go into its zip under `__source/`,
// with a manifest from DWARF path to zip path. Copied from posthog-cli's `dsym/source_bundle.rs`,
// so the paths found, their zip names and the bytes of the manifest are the ones posthog-cli
// writes. hog applies its ignore patterns between `extract` and `collect`.

use anyhow::Result;
use serde::Serialize;
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs, io,
    io::{Read, Seek, Write},
    path::Path,
};
use symbolic::debuginfo::{
    dwarf::{gimli, Dwarf as DwarfObject},
    Archive, Object,
};

use crate::node;

const MAX_SOURCE_FILE_BYTES: u64 = 64 * 1024 * 1024;
const MANIFEST_VERSION: u32 = 1;
const MANIFEST_ENTRY: &str = "__source/manifest.json";
const SOURCE_FOLDER: &str = "__source";
// A name that several files share takes one more parent folder per round, up to this many rounds.
const MAX_DISAMBIGUATION_ROUNDS: usize = 10;

const REFUSED_SYMLINK: &str = "path is a symlink";
const REFUSED_NOT_A_FILE: &str = "not a regular file";
const REFUSED_TOO_LARGE: &str = "exceeds the source file size limit";

// Short root-level names that Apple's linker writes as placeholder compile unit names for system
// frameworks. They are not files, and they would drag the project prefix down to `/`.
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
const EXCLUDED_PREFIXES: &[&str] = &[
    "/usr/",
    "/Library/Developer/",
    "/Applications/Xcode",
    "/System/",
];
const EXCLUDED_SUBSTRINGS: &[&str] = &[
    "/Xcode.app/",
    "/SDKs/",
    "<compiler-generated>",
    "<built-in>",
    "/DerivedData/",
];
// Registry and toolchain sources, which sit outside the project of a Rust or Go build.
const NATIVE_EXCLUDED: &[&str] = &[
    "/.cargo/registry/",
    "/.cargo/git/",
    "/rustc/",
    "/.rustup/toolchains/",
    "/vendor/",
];
// Every Go binary compiles in the runtime package, so a folder whose `src/runtime/` holds all of
// these is a GOROOT, wherever the toolchain was installed.
const GOROOT_WITNESSES: &[&str] = &[
    "runtime/proc.go",
    "runtime/malloc.go",
    "runtime/mgc.go",
    "runtime/runtime2.go",
];
const GOROOT_MARKER: &str = "/src/runtime/proc.go";
const GOROOT_SOURCE_FOLDER: &str = "/src/";
const GO_MODULE_CACHE: &str = "/pkg/mod/";

#[derive(Clone, Copy)]
pub enum Filter {
    // `dsym upload`: system, SDK and generated paths go.
    Dsym,
    // `symbol-sets upload`: registry and toolchain paths go too.
    Native,
}

#[derive(Serialize)]
struct SourceManifest {
    version: u32,
    // From the path the DWARF names to the path inside the zip. Sorted, so the manifest is the
    // same on every run.
    files: BTreeMap<String, String>,
}

pub struct SourceFiles {
    manifest: SourceManifest,
    // From zip path to contents. A later file with the same zip path replaces the earlier one.
    contents: BTreeMap<String, Vec<u8>>,
}

#[derive(Serialize)]
pub struct Unreadable {
    path: String,
    message: String,
}

// The source paths of one binary, filtered for its upload path. An error means the DWARF could
// not be read, and the binary uploads without sources.
pub fn extract(data: &[u8], filter: Filter) -> Result<Vec<String>> {
    let paths = extract_source_paths(data)?;

    Ok(paths
        .into_iter()
        .filter(|path| is_user_source(path))
        .filter(|path| match filter {
            Filter::Dsym => true,
            Filter::Native => !NATIVE_EXCLUDED.iter().any(|sub| path.contains(sub)),
        })
        .collect())
}

// A walk over compile units alone misses files that Swift whole-module optimization inlines into
// another unit, and a walk over every line table also finds the sources of imported frameworks,
// which change the zip when a dependency is rebuilt. So the compile units give the project
// folder, and the line tables give every file under it.
fn extract_source_paths(data: &[u8]) -> Result<Vec<String>> {
    let archive = Archive::parse(data)?;

    let mut paths: HashSet<String> = HashSet::new();
    let mut any_go = false;
    for object in archive.objects() {
        let object = object?;

        // A Go compile unit names a package, not a file, so it gives no prefix. For Go the line
        // table decides: absolute `.go` and `.s` paths stay.
        let units = compile_unit_files(&object);
        any_go |= units.has_go;
        let project_prefix = longest_common_prefix(&units.main_files);

        let session = object.debug_session()?;
        for file in session.files() {
            let path = file?.abs_path_str();
            if path.is_empty() {
                continue;
            }

            let in_project = match &project_prefix {
                Some(prefix) => {
                    path.starts_with(prefix.as_str())
                        || (units.has_go && is_bundleable_go_source(&path))
                }
                None if units.has_go => is_bundleable_go_source(&path),
                None => true,
            };
            if in_project {
                paths.insert(path);
            }
        }
    }

    let mut paths: Vec<String> = paths.into_iter().collect();
    paths.sort();
    if any_go {
        paths = filter_go_toolchain_sources(paths);
    }
    Ok(paths)
}

// A line table entry can name any file, because a `//line` directive in a dependency sets it. An
// absolute path with a Go source extension and no dot components keeps the files read to sources,
// and keeps `..` out of the zip names derived from it.
fn is_bundleable_go_source(path: &str) -> bool {
    let bytes = path.as_bytes();
    let absolute = path.starts_with('/')
        || (bytes.len() > 2
            && bytes[0].is_ascii_alphabetic()
            && bytes[1] == b':'
            && matches!(bytes[2], b'/' | b'\\'));
    let normalized = !path
        .split(['/', '\\'])
        .any(|component| component == "." || component == "..");

    absolute && normalized && is_go_source(path)
}

fn is_go_source(path: &str) -> bool {
    path.ends_with(".go") || path.ends_with(".s")
}

// Matching runs on copies with `/` separators, so an ELF built on Windows meets the same filters.
fn filter_go_toolchain_sources(paths: Vec<String>) -> Vec<String> {
    let normalize = |path: &str| path.replace('\\', "/");
    let normalized: HashSet<String> = paths.iter().map(|path| normalize(path)).collect();
    let goroot_sources: Vec<String> = normalized
        .iter()
        .filter_map(|path| {
            path.find(GOROOT_MARKER)
                .map(|at| path[..at + GOROOT_SOURCE_FOLDER.len()].to_string())
        })
        .filter(|root| {
            GOROOT_WITNESSES
                .iter()
                .all(|witness| normalized.contains(&format!("{root}{witness}")))
        })
        .collect();

    paths
        .into_iter()
        .filter(|path| {
            let path = normalize(path);
            !path.contains(GO_MODULE_CACHE)
                && !goroot_sources
                    .iter()
                    .any(|root| path.starts_with(root.as_str()))
        })
        .collect()
}

#[derive(Default)]
struct CompileUnits {
    // The main file of each compile unit that is not Go.
    main_files: Vec<String>,
    has_go: bool,
}

fn compile_unit_files(object: &Object<'_>) -> CompileUnits {
    match object {
        Object::MachO(macho) => compile_unit_files_from_dwarf(macho),
        Object::Elf(elf) => compile_unit_files_from_dwarf(elf),
        _ => CompileUnits::default(),
    }
}

// Reads the root entry of each unit and never a line program, so files that only a line table
// names, like the declaration sites of imported frameworks, stay out of the project prefix.
fn compile_unit_files_from_dwarf<'data>(object: &impl DwarfObject<'data>) -> CompileUnits {
    let empty: &[u8] = &[];
    let section = |name: &str| {
        object
            .section(name)
            .map(|section| section.data.into_owned())
            .unwrap_or_default()
    };
    let info = section("debug_info");
    let abbrev = section("debug_abbrev");
    let strings = section("debug_str");
    let line_strings = section("debug_line_str");

    let endian = if matches!(object.endianity(), gimli::RunTimeEndian::Big) {
        gimli::RunTimeEndian::Big
    } else {
        gimli::RunTimeEndian::Little
    };
    let dwarf = gimli::Dwarf {
        debug_info: gimli::DebugInfo::new(&info, endian),
        debug_abbrev: gimli::DebugAbbrev::new(&abbrev, endian),
        debug_str: gimli::DebugStr::new(&strings, endian),
        debug_line_str: gimli::DebugLineStr::new(&line_strings, endian),
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

    let text = |slice: gimli::EndianSlice<'_, gimli::RunTimeEndian>| {
        std::str::from_utf8(slice.slice()).ok().map(str::to_string)
    };
    let resolve =
        |value: gimli::AttributeValue<gimli::EndianSlice<'_, gimli::RunTimeEndian>>| match value {
            gimli::AttributeValue::String(string) => text(string),
            gimli::AttributeValue::DebugStrRef(offset) => {
                dwarf.debug_str.get_str(offset).ok().and_then(text)
            }
            gimli::AttributeValue::DebugLineStrRef(offset) => {
                dwarf.debug_line_str.get_str(offset).ok().and_then(text)
            }
            _ => None,
        };

    let mut units = CompileUnits::default();
    let mut headers = dwarf.units();
    while let Ok(Some(header)) = headers.next() {
        let Ok(abbreviations) = dwarf.abbreviations(&header) else {
            continue;
        };
        let mut cursor = header.entries(&abbreviations);
        let root = match cursor.next_dfs() {
            Ok(Some((_, entry))) => entry,
            _ => continue,
        };
        if root.tag() != gimli::DW_TAG_compile_unit {
            continue;
        }

        if matches!(
            root.attr_value(gimli::DW_AT_language),
            Ok(Some(gimli::AttributeValue::Language(gimli::DW_LANG_Go)))
        ) {
            units.has_go = true;
            continue;
        }

        let folder = root
            .attr_value(gimli::DW_AT_comp_dir)
            .ok()
            .flatten()
            .and_then(&resolve);
        let name = root
            .attr_value(gimli::DW_AT_name)
            .ok()
            .flatten()
            .and_then(&resolve);
        let path = match (folder, name) {
            // Swift writes units named `<swift-imported-modules>` next to a real folder. Joined,
            // the name would pass the synthetic-name filter and take over the project prefix.
            (_, Some(name)) if name.starts_with('<') => continue,
            (Some(folder), Some(name)) if !name.starts_with('/') => {
                format!("{}/{}", folder.trim_end_matches('/'), name)
            }
            (_, Some(name)) if name.starts_with('/') => name,
            (Some(folder), None) => folder,
            _ => continue,
        };

        if !path.is_empty() {
            units.main_files.push(path);
        }
    }

    units.main_files.retain(|path| {
        !EXCLUDED_SYNTHETIC_NAMES
            .iter()
            .any(|name| path.starts_with(name))
            && !EXCLUDED_PREFIXES
                .iter()
                .any(|prefix| path.starts_with(prefix))
            && !EXCLUDED_SUBSTRINGS.iter().any(|sub| path.contains(sub))
    });
    units
}

// The longest folder that every path is under. File names are cut off first, so two files in one
// folder share the whole folder and not just the start of their names.
fn longest_common_prefix(paths: &[String]) -> Option<String> {
    let folders: Vec<&str> = paths
        .iter()
        .map(|path| match path.rfind('/') {
            Some(slash) => &path[..=slash],
            None => "/",
        })
        .collect();

    let first = *folders.first()?;
    let mut prefix_length = first.len();
    for folder in &folders[1..] {
        let shared = first
            .char_indices()
            .zip(folder.chars())
            .take_while(|((_, a), b)| a == b)
            .last()
            .map(|((position, character), _)| position + character.len_utf8())
            .unwrap_or(0);
        let at_folder = first[..shared].rfind('/').map_or(0, |slash| slash + 1);
        prefix_length = prefix_length.min(at_folder);
    }

    (prefix_length > 0).then(|| first[..prefix_length].to_string())
}

// Go sources keep system prefixes: a containerized Go build often sits under /usr/src, and the
// Go toolchain's own trees are already gone.
fn is_user_source(path: &str) -> bool {
    let system = !is_go_source(path)
        && EXCLUDED_PREFIXES
            .iter()
            .any(|prefix| path.starts_with(prefix));

    !system
        && !EXCLUDED_SUBSTRINGS.iter().any(|sub| path.contains(sub))
        && !EXCLUDED_SYNTHETIC_NAMES
            .iter()
            .any(|name| path.starts_with(name))
}

// O_NOFOLLOW keeps a path swapped for a symlink after the check from being followed. O_NONBLOCK
// keeps the open of a FIFO without a writer from hanging before the regular-file check refuses it.
#[cfg(unix)]
fn open_source(path: &Path) -> io::Result<fs::File> {
    use std::os::unix::fs::OpenOptionsExt;

    fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
}

// Windows has no flag like O_NOFOLLOW in std, and a symlink there needs elevated rights to
// create, so the check before the open has to do.
#[cfg(not(unix))]
fn open_source(path: &Path) -> io::Result<fs::File> {
    fs::File::open(path)
}

// A path from DWARF can point anywhere, so symlinks, devices and files over the limit are refused,
// and the checks run on the opened file, which nothing can swap between the check and the read.
// The failures read as they did when hog read these files itself.
fn read_source_file(path: &Path) -> Result<Vec<u8>, String> {
    let failed =
        |syscall: &'static str| move |error: io::Error| node::message(&error, syscall, path);

    let link = fs::symlink_metadata(path).map_err(failed("lstat"))?;
    if link.file_type().is_symlink() {
        return Err(REFUSED_SYMLINK.to_string());
    }
    let file = open_source(path).map_err(failed("open"))?;
    let metadata = file.metadata().map_err(failed("fstat"))?;
    if !metadata.is_file() {
        return Err(REFUSED_NOT_A_FILE.to_string());
    }
    if metadata.len() > MAX_SOURCE_FILE_BYTES {
        return Err(REFUSED_TOO_LARGE.to_string());
    }

    // One byte past the limit is read, so a file that grew after the check fails instead of
    // going into the zip cut short.
    let mut data = Vec::with_capacity(metadata.len() as usize);
    file.take(MAX_SOURCE_FILE_BYTES + 1)
        .read_to_end(&mut data)
        .map_err(failed("read"))?;
    if data.len() as u64 > MAX_SOURCE_FILE_BYTES {
        return Err(REFUSED_TOO_LARGE.to_string());
    }
    Ok(data)
}

// Starts from file names, then gives every name that several files share one more parent folder
// per round. Dot components never tell two files apart, and a `..` would land in a zip entry name,
// where a crafted DWARF path could leave `__source/` when the zip is extracted.
fn zip_relative_paths(paths: &[String]) -> Vec<String> {
    let mut names: Vec<String> = paths
        .iter()
        .map(|path| {
            Path::new(path)
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("unknown")
                .to_string()
        })
        .collect();

    for _ in 0..MAX_DISAMBIGUATION_ROUNDS {
        let mut places: HashMap<String, Vec<usize>> = HashMap::new();
        for (place, name) in names.iter().enumerate() {
            places.entry(name.clone()).or_default().push(place);
        }

        let mut has_duplicates = false;
        for shared in places.values().filter(|shared| shared.len() > 1) {
            has_duplicates = true;
            for &place in shared {
                let components: Vec<&str> = paths[place]
                    .split('/')
                    .filter(|part| !part.is_empty() && *part != "." && *part != "..")
                    .collect();
                let depth = (names[place].matches('/').count() + 2).min(components.len());
                names[place] = components[components.len() - depth..].join("/");
            }
        }
        if !has_duplicates {
            break;
        }
    }
    names
}

// Reads the files hog allowed. A file that can't be read is reported and left out, and the
// manifest is written even when every read failed.
pub fn collect(paths: &[String]) -> (SourceFiles, Vec<Unreadable>) {
    let mut files = BTreeMap::new();
    let mut contents = BTreeMap::new();
    let mut unreadable = Vec::new();

    for (path, relative) in paths.iter().zip(zip_relative_paths(paths)) {
        match read_source_file(Path::new(path)) {
            Ok(data) => {
                let zip_path = format!("{SOURCE_FOLDER}/{relative}");
                files.insert(path.clone(), zip_path.clone());
                contents.insert(zip_path, data);
            }
            Err(message) => unreadable.push(Unreadable {
                path: path.clone(),
                message,
            }),
        }
    }

    let manifest = SourceManifest {
        version: MANIFEST_VERSION,
        files,
    };
    (SourceFiles { manifest, contents }, unreadable)
}

// The manifest, then every file in the byte order of its zip path.
pub fn add_to_zip<W: Write + Seek>(
    zip: &mut zip::ZipWriter<W>,
    sources: &SourceFiles,
) -> Result<()> {
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    zip.start_file(MANIFEST_ENTRY, options)?;
    zip.write_all(&serde_json::to_vec_pretty(&sources.manifest)?)?;

    for (zip_path, data) in &sources.contents {
        zip.start_file(zip_path.clone(), options)?;
        zip.write_all(data)?;
    }
    Ok(())
}
