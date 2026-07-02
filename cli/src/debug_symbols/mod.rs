use std::path::{Path, PathBuf};

use anyhow::{anyhow, Result};
use posthog_symbol_data::{write_symbol_data, ElfDebugInfo};
use symbolic::debuginfo::{Archive, FileFormat, ObjectKind};
use tracing::{info, warn};

use crate::api::symbol_sets::SymbolSetUpload;
use crate::dsym::source_bundle;

pub mod upload;

const ELF_MAGIC: &[u8; 4] = b"\x7fELF";

/// A native debug-info file discovered on disk, parsed and validated,
/// ready to be packaged for upload.
pub struct DebugSymbolFile {
    /// The debug id derived from the GNU build id (used as chunk_id)
    pub debug_id: String,
    pub path: PathBuf,
    /// Raw file contents
    data: Vec<u8>,
    /// Size of the file, used to pick the richer candidate on debug_id collisions
    size: usize,
}

/// The outcome of scanning a directory for native debug symbols.
#[derive(Default)]
pub struct DiscoveryReport {
    /// Validated files, deduplicated by debug id
    pub files: Vec<DebugSymbolFile>,
    /// ELF executables/libraries that carry no debug info (skipped)
    pub without_debug_info: Vec<PathBuf>,
    /// ELFs with debug info but no GNU build id (cannot be uploaded)
    pub missing_build_id: Vec<PathBuf>,
    /// dSYM bundles spotted while scanning (handled by `dsym upload`)
    pub dsym_bundles: Vec<PathBuf>,
    /// Split-DWARF artifacts spotted while scanning (unsupported)
    pub split_dwarf: Vec<PathBuf>,
}

impl DebugSymbolFile {
    /// Package the file for upload: a ZIP with the binary stored as `dwarf` at
    /// the root (plus an optional `__source/` bundle), wrapped in the
    /// `ElfDebugInfo` symbol_data container.
    pub fn into_upload(
        self,
        release_id: Option<String>,
        include_source: bool,
    ) -> Result<SymbolSetUpload> {
        use std::io::{Cursor, Write};

        let mut buffer = Cursor::new(Vec::new());
        {
            let mut zip = zip::ZipWriter::new(&mut buffer);
            let options = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);

            zip.start_file("dwarf", options)?;
            zip.write_all(&self.data)?;

            if include_source {
                match source_bundle::extract_source_paths_from_dwarf_bytes(&self.data) {
                    Ok(all_paths) => {
                        let filtered = filter_native_source_paths(&all_paths);
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
                                    warn!("Failed to collect source files: {} (continuing without source)", e);
                                }
                            }
                        }
                    }
                    Err(e) => {
                        warn!(
                            "Failed to extract DWARF source paths: {} (continuing without source)",
                            e
                        );
                    }
                }
            }

            zip.finish()?;
        }

        let wrapped = write_symbol_data(ElfDebugInfo {
            data: buffer.into_inner(),
        })?;

        Ok(SymbolSetUpload {
            chunk_id: self.debug_id,
            release_id,
            data: wrapped,
        })
    }
}

/// Filter DWARF source paths for native (Rust/C/C++) builds: on top of the
/// shared system-path filters, drop registry/toolchain sources that aren't
/// part of the user's project tree.
fn filter_native_source_paths(paths: &[String]) -> Vec<&str> {
    source_bundle::filter_source_paths(paths)
        .into_iter()
        .filter(|path| {
            const EXCLUDED: &[&str] = &[
                "/.cargo/registry/",
                "/.cargo/git/",
                "/rustc/",
                "/.rustup/toolchains/",
                "/vendor/",
            ];
            if EXCLUDED.iter().any(|sub| path.contains(sub)) {
                tracing::debug!("Filtered out (native toolchain): {}", path);
                return false;
            }
            true
        })
        .collect()
}

/// Walk `directory` and classify everything that looks like native debug
/// symbols. Only ELF executables, shared libraries, and debug companions
/// (e.g. from `objcopy --only-keep-debug`) are considered; relocatable
/// objects and other ELF kinds are ignored.
pub fn discover(directory: &Path) -> Result<DiscoveryReport> {
    use walkdir::WalkDir;

    let mut report = DiscoveryReport::default();
    let mut seen: std::collections::HashMap<String, usize> = std::collections::HashMap::new();

    for entry in WalkDir::new(directory).follow_links(true) {
        // A symlink loop, dangling link, or unreadable directory surfaces here
        // as an iterator error. Skip just that entry rather than aborting the
        // whole scan, which would discard every valid file already found.
        let entry = match entry {
            Ok(entry) => entry,
            Err(e) => {
                warn!("Skipping unreadable path while scanning: {e}");
                continue;
            }
        };
        let path = entry.path();

        if path.is_dir() {
            if path.extension().is_some_and(|e| e == "dSYM") {
                report.dsym_bundles.push(path.to_path_buf());
            }
            continue;
        }

        if path.extension().is_some_and(|e| e == "dwp" || e == "dwo") {
            report.split_dwarf.push(path.to_path_buf());
            continue;
        }

        if !entry.file_type().is_file() {
            continue;
        }

        let Some(file) = parse_candidate(path)? else {
            continue;
        };

        match file {
            Candidate::NoDebugInfo => report.without_debug_info.push(path.to_path_buf()),
            Candidate::NoBuildId => report.missing_build_id.push(path.to_path_buf()),
            Candidate::Valid(file) => {
                // Dedup by debug id (e.g. a binary and its objcopy companion):
                // keep the larger file, which carries at least as much debug data.
                if let Some(&existing) = seen.get(&file.debug_id) {
                    let existing_file = &report.files[existing];
                    warn!(
                        "Duplicate debug id {} for {} and {}; keeping the larger file",
                        file.debug_id,
                        existing_file.path.display(),
                        file.path.display()
                    );
                    if file.size > existing_file.size {
                        report.files[existing] = file;
                    }
                } else {
                    seen.insert(file.debug_id.clone(), report.files.len());
                    report.files.push(file);
                }
            }
        }
    }

    Ok(report)
}

enum Candidate {
    Valid(DebugSymbolFile),
    NoDebugInfo,
    NoBuildId,
}

fn has_elf_magic(path: &Path) -> bool {
    use std::io::Read;

    let Ok(mut file) = std::fs::File::open(path) else {
        warn!("Could not open {} (skipping)", path.display());
        return false;
    };
    let mut magic = [0u8; ELF_MAGIC.len()];
    file.read_exact(&mut magic).is_ok() && &magic == ELF_MAGIC
}

/// Parse a file as a native debug-symbol candidate. Returns `None` for
/// anything that isn't an ELF executable/library/debug companion.
fn parse_candidate(path: &Path) -> Result<Option<Candidate>> {
    // Check the magic before loading the file: build trees contain large
    // non-ELF artifacts that shouldn't be read into memory just to be skipped.
    if !has_elf_magic(path) {
        return Ok(None);
    }

    let Ok(data) = std::fs::read(path) else {
        warn!("Could not read {} (skipping)", path.display());
        return Ok(None);
    };

    // Scope the parsed archive so `data` can move into the result afterwards.
    let debug_id = {
        let archive = match Archive::parse(&data) {
            Ok(archive) => archive,
            Err(e) => {
                warn!("Could not parse {} as ELF: {e} (skipping)", path.display());
                return Ok(None);
            }
        };

        let Some(Ok(object)) = archive.objects().next() else {
            warn!("No objects in {} (skipping)", path.display());
            return Ok(None);
        };

        if object.file_format() != FileFormat::Elf {
            return Ok(None);
        }

        // Relocatable objects (.o) and other kinds aren't loadable images.
        if !matches!(
            object.kind(),
            ObjectKind::Executable | ObjectKind::Library | ObjectKind::Debug
        ) {
            return Ok(None);
        }

        if !object.has_debug_info() {
            return Ok(Some(Candidate::NoDebugInfo));
        }

        // Without a GNU build id (code id), symbolic synthesizes a
        // content-derived debug id that the SDK cannot reproduce at runtime,
        // so the upload would never match any crash event.
        if object.code_id().is_none() {
            return Ok(Some(Candidate::NoBuildId));
        }

        let debug_id = object.debug_id();
        if debug_id.is_nil() {
            return Ok(Some(Candidate::NoBuildId));
        }
        debug_id.to_string()
    };

    let size = data.len();
    Ok(Some(Candidate::Valid(DebugSymbolFile {
        debug_id,
        path: path.to_path_buf(),
        data,
        size,
    })))
}

/// Render guidance for files that couldn't be uploaded; returns an error when
/// nothing usable was found at all.
pub fn report_problems(report: &DiscoveryReport, directory: &Path) -> Result<()> {
    if !report.split_dwarf.is_empty() {
        warn!(
            "Found {} split-DWARF file(s) (.dwp/.dwo), which aren't supported yet. \
             Build with debug info embedded in the binary (the default on Linux), \
             or upload an `objcopy --only-keep-debug` companion instead.",
            report.split_dwarf.len()
        );
    }

    for path in &report.without_debug_info {
        warn!(
            "{} has no debug info (skipping). For release builds, set \
             `debug = \"line-tables-only\"` (or `true`) in [profile.release], \
             and upload before stripping.",
            path.display()
        );
    }

    if !report.missing_build_id.is_empty() {
        let listing = report
            .missing_build_id
            .iter()
            .map(|p| format!("  {}", p.display()))
            .collect::<Vec<_>>()
            .join("\n");
        let guidance = format!(
            "The following files have debug info but no GNU build id, so they cannot be \
             matched to crash events:\n{listing}\n\
             Link with `-Wl,--build-id=sha1` (in Rust: `-C link-arg=-Wl,--build-id=sha1` \
             via RUSTFLAGS; in Go: `-ldflags=-B=gobuildid`); most C/C++/Rust \
             toolchains add this by default, Go does not."
        );
        // Only fail the run when there's nothing valid to upload; otherwise a
        // stray build-id-less helper binary would block every valid symbol.
        if report.files.is_empty() {
            anyhow::bail!("{guidance}");
        }
        warn!("{guidance}");
    }

    if report.files.is_empty() {
        if !report.dsym_bundles.is_empty() {
            anyhow::bail!(
                "No ELF debug symbols found in {}, but {} dSYM bundle(s) were. \
                 Use `posthog-cli dsym upload` for Apple dSYMs.",
                directory.display(),
                report.dsym_bundles.len()
            );
        }
        anyhow::bail!(
            "No ELF files with debug info found in {}",
            directory.display()
        );
    }

    if !report.dsym_bundles.is_empty() {
        warn!(
            "Skipping {} dSYM bundle(s); use `posthog-cli dsym upload` for those.",
            report.dsym_bundles.len()
        );
    }

    Ok(())
}

/// Extract the debug id of an ELF file, e.g. for testing parity with the SDK.
pub fn elf_debug_id(path: &Path) -> Result<String> {
    let data = std::fs::read(path)?;
    let archive = Archive::parse(&data).map_err(|e| anyhow!("parse {}: {e}", path.display()))?;
    let object = archive
        .objects()
        .next()
        .ok_or_else(|| anyhow!("no objects in {}", path.display()))?
        .map_err(|e| anyhow!("parse object in {}: {e}", path.display()))?;
    Ok(object.debug_id().to_string())
}
