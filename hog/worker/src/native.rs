// Native debug symbols: ELF files, Mach-O files and the slices of dSYM bundles. Copied from
// posthog-cli's `debug_symbols/mod.rs` and `dsym/mod.rs`, and parsed, zipped and wrapped with the
// crates posthog-cli uses, so a symbol set and its content hash are the ones PostHog stores for a
// posthog-cli upload.

use anyhow::Result;
use posthog_symbol_data::{write_symbol_data, AppleDsym, ElfDebugInfo};
use serde::Serialize;
use std::{
    fs,
    io::{Cursor, Read, Write},
    ops::Range,
    path::Path,
    sync::Arc,
};
use symbolic::debuginfo::{Archive, FileFormat, Object, ObjectKind};

use crate::{
    node,
    sources::{self, SourceFiles},
    upload::{content_hash, write_container},
};

const ELF_MAGIC: [u8; 4] = *b"\x7fELF";
// Thin little-endian Mach-O with 64-bit and 32-bit headers, and the 32-bit fat header. A
// big-endian Mach-O and a 64-bit fat file are not native files to posthog-cli.
const FAT_MAGIC: [u8; 4] = [0xca, 0xfe, 0xba, 0xbe];
const MACHO_MAGICS: [[u8; 4]; 3] = [
    [0xcf, 0xfa, 0xed, 0xfe],
    [0xce, 0xfa, 0xed, 0xfe],
    FAT_MAGIC,
];
// Go's linker on macOS compresses DWARF into sections with this prefix. A section name sits in
// the section headers as written, so a scan of the bytes finds it.
const COMPRESSED_DWARF_MARKER: &[u8] = b"__zdebug_";
const DWARF_ENTRY: &str = "dwarf";
const CONTAINER_PREFIX: &str = "native";
const CONTAINER_EXTENSION: &str = "symbolset";

#[derive(Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Format {
    Elf,
    Macho,
}

pub fn magic_format(path: &Path) -> Option<Format> {
    let mut magic = [0u8; 4];
    fs::File::open(path).ok()?.read_exact(&mut magic).ok()?;

    if magic == ELF_MAGIC {
        Some(Format::Elf)
    } else if MACHO_MAGICS.contains(&magic) {
        Some(Format::Macho)
    } else {
        None
    }
}

// One binary that uploads as one symbol set: a whole ELF or thin Mach-O file, or one architecture
// of a fat Mach-O. The file is shared, so the slices of a fat file hold it once.
pub struct Binary {
    file: Arc<Vec<u8>>,
    range: Range<usize>,
    format: Format,
    // A slice of a dSYM bundle reads its sources from the whole file, so every architecture of a
    // fat file carries the sources of all of them, as `posthog-cli dsym upload` packs them.
    from_dsym: bool,
}

impl Binary {
    pub fn new(file: Arc<Vec<u8>>, range: Range<usize>, format: Format, from_dsym: bool) -> Self {
        Binary {
            file,
            range,
            format,
            from_dsym,
        }
    }

    pub fn format(&self) -> Format {
        self.format
    }

    pub fn size(&self) -> usize {
        self.range.len()
    }

    fn data(&self) -> &[u8] {
        &self.file[self.range.clone()]
    }

    pub fn source_paths(&self) -> Result<Vec<String>> {
        if self.from_dsym {
            sources::extract(&self.file, sources::Filter::Dsym)
        } else {
            sources::extract(self.data(), sources::Filter::Native)
        }
    }
}

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Problem {
    NoDebugInfo,
    NoBuildId,
    MissingUuid,
    CompressedDwarf,
    UnparseableSlice,
}

pub enum Candidate {
    Problem(Problem),
    Valid { debug_id: String, binary: Binary },
}

// Where `part` sits inside `whole`. symbolic hands out an object's bytes as a slice of the bytes
// it parsed.
pub fn range_within(whole: &[u8], part: &[u8]) -> Range<usize> {
    let start = (part.as_ptr() as usize).saturating_sub(whole.as_ptr() as usize);

    start..start + part.len()
}

// What one file holds: a candidate for each architecture of a fat Mach-O, and none for an object
// that is not an executable, a library or a debug companion. An error means the file can't be
// read or parsed at all.
pub fn candidates(path: &Path) -> Result<Vec<Candidate>, String> {
    let file = Arc::new(node::read(path)?);
    let archive = Archive::parse(&file).map_err(|error| error.to_string())?;

    let mut candidates = Vec::new();
    for object in archive.objects() {
        let object = match object {
            Ok(object) => object,
            // The other architectures of a fat file stay usable. A thin file is its only object.
            Err(_) if file.starts_with(&FAT_MAGIC) => {
                candidates.push(Candidate::Problem(Problem::UnparseableSlice));
                continue;
            }
            Err(error) => return Err(error.to_string()),
        };
        let format = match object.file_format() {
            FileFormat::Elf => Format::Elf,
            FileFormat::MachO => Format::Macho,
            _ => continue,
        };
        if !matches!(
            object.kind(),
            ObjectKind::Executable | ObjectKind::Library | ObjectKind::Debug
        ) {
            continue;
        }

        candidates.push(match problem(&object, format) {
            Some(problem) => Candidate::Problem(problem),
            None => {
                // Chunk ids are case-sensitive in PostHog: ELF ids are lowercase and Mach-O ids
                // uppercase, as the SDKs report them.
                let debug_id = match format {
                    Format::Macho => object.debug_id().to_string().to_uppercase(),
                    Format::Elf => object.debug_id().to_string(),
                };
                let range = range_within(&file, object.data());
                Candidate::Valid {
                    debug_id,
                    binary: Binary::new(file.clone(), range, format, false),
                }
            }
        });
    }
    Ok(candidates)
}

fn problem(object: &Object<'_>, format: Format) -> Option<Problem> {
    if !object.has_debug_info() {
        let compressed = format == Format::Macho
            && object
                .data()
                .windows(COMPRESSED_DWARF_MARKER.len())
                .any(|window| window == COMPRESSED_DWARF_MARKER);
        return Some(if compressed {
            Problem::CompressedDwarf
        } else {
            Problem::NoDebugInfo
        });
    }

    // symbolic derives a debug id from the contents of an ELF without a build id, which no SDK
    // can reproduce when the program runs, so the code id decides for ELF.
    let unidentified =
        (format == Format::Elf && object.code_id().is_none()) || object.debug_id().is_nil();
    unidentified.then_some(match format {
        Format::Macho => Problem::MissingUuid,
        Format::Elf => Problem::NoBuildId,
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Built {
    content_hash: String,
    size: usize,
    // Null in a dry run, which writes nothing.
    path: Option<String>,
}

// A zip with the binary as `dwarf` and the sources after it, wrapped in the container of the
// binary's format, and written to `<folder>/native-<id>.symbolset`.
pub fn pack(
    id: usize,
    binary: &Binary,
    sources: Option<&SourceFiles>,
    folder: Option<&Path>,
) -> Result<Built> {
    let mut buffer = Cursor::new(Vec::new());
    {
        let mut zip = zip::ZipWriter::new(&mut buffer);
        let options = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);

        zip.start_file(DWARF_ENTRY, options)?;
        zip.write_all(binary.data())?;
        if let Some(sources) = sources {
            sources::add_to_zip(&mut zip, sources)?;
        }
        zip.finish()?;
    }

    let data = buffer.into_inner();
    let container = match binary.format {
        Format::Macho => write_symbol_data(AppleDsym { data })?,
        Format::Elf => write_symbol_data(ElfDebugInfo { data })?,
    };

    let path = match folder {
        Some(folder) => {
            let path = folder.join(format!("{CONTAINER_PREFIX}-{id}.{CONTAINER_EXTENSION}"));
            write_container(&path, &container)?;
            Some(path.to_string_lossy().into_owned())
        }
        None => None,
    };

    Ok(Built {
        content_hash: content_hash([&container]),
        size: container.len(),
        path,
    })
}
