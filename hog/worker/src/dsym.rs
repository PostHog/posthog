// posthog-cli asks `dwarfdump --uuid` and `lipo -thin` for the slices of a dSYM bundle, which only
// a Mac with Xcode has. The worker reads the fat header and the UUIDs itself, so a dSYM uploads
// from any machine with the bytes those tools give.

use std::{ops::Range, path::Path, sync::Arc};
use symbolic::debuginfo::{Archive, FileFormat};

use crate::{
    native::{Binary, Format},
    node,
};

const FAT_MAGIC: u32 = 0xcafe_babe;
// symbolic does not read a fat file with 64-bit offsets, and `dwarfdump` and `lipo` do.
const FAT_MAGIC_64: u32 = 0xcafe_babf;
const FAT_HEADER_LENGTH: usize = 8;
const FAT_ARCH_LENGTH: usize = 20;
const FAT_ARCH_64_LENGTH: usize = 32;
// The offset and the size follow the CPU type and subtype, which are 4 bytes each.
const FAT_ARCH_OFFSET_FIELD: usize = 8;
// A Java class file starts with the same 4 bytes, followed by its version where a fat file has its
// count. symbolic reads 45 or more as a class file, and no fat file has that many architectures.
const MIN_JAVA_CLASS_VERSION: u32 = 45;

pub struct Slice {
    pub uuid: String,
    pub binary: Binary,
}

fn big_endian(bytes: &[u8], at: usize, width: usize) -> Option<u64> {
    let field = bytes.get(at..at + width)?;

    Some(
        field
            .iter()
            .fold(0, |value, byte| (value << 8) | u64::from(*byte)),
    )
}

// None for a thin file, which is one slice as a whole. A range the file is too short for is cut
// to the file, and the slice then fails to parse.
fn fat_slices(file: &[u8]) -> Option<Vec<Range<usize>>> {
    let magic = big_endian(file, 0, 4)? as u32;
    let count = big_endian(file, 4, 4)? as u32;
    let (entry_length, field_width) = match magic {
        FAT_MAGIC => (FAT_ARCH_LENGTH, 4),
        FAT_MAGIC_64 => (FAT_ARCH_64_LENGTH, 8),
        _ => return None,
    };
    if count >= MIN_JAVA_CLASS_VERSION {
        return None;
    }

    let clamp = |value: u64| usize::try_from(value).unwrap_or(usize::MAX).min(file.len());
    (0..count as usize)
        .map(|index| {
            let entry = FAT_HEADER_LENGTH + index * entry_length + FAT_ARCH_OFFSET_FIELD;
            let offset = big_endian(file, entry, field_width)?;
            let size = big_endian(file, entry + field_width, field_width)?;

            Some(clamp(offset)..clamp(offset.saturating_add(size)))
        })
        .collect()
}

pub fn slices(path: &Path) -> Result<Vec<Slice>, String> {
    let file = Arc::new(node::read(path)?);
    let whole = std::iter::once(0..file.len()).collect();
    let ranges = fat_slices(&file).unwrap_or(whole);

    let mut slices = Vec::new();
    for range in ranges {
        let archive = Archive::parse(&file[range.clone()]).map_err(|error| error.to_string())?;
        let Some(object) = archive.objects().next() else {
            continue;
        };
        let object = object.map_err(|error| error.to_string())?;

        if object.file_format() == FileFormat::MachO && !object.debug_id().is_nil() {
            slices.push(Slice {
                uuid: object.debug_id().to_string().to_uppercase(),
                binary: Binary::new(file.clone(), range, Format::Macho, true),
            });
        }
    }
    Ok(slices)
}
