use std::path::Path;

use anyhow::Result;
use tracing::warn;

pub use posthog_symbol_processing::debug_symbols::{
    discover, elf_debug_id, package_dsym_bundles, DebugSymbolFile, DiscoveryReport,
};

pub mod upload;

/// Render guidance for files that couldn't be uploaded; returns an error when
/// nothing usable was found at all.
pub fn report_problems(report: &DiscoveryReport, directory: &Path) -> Result<()> {
    // ELF debug files and dSYM bundles are both uploaded by `symbol-sets upload`
    // now, so the only genuinely empty case is when neither was found.
    let nothing_to_upload = report.files.is_empty() && report.dsym_bundles.is_empty();

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

    for path in &report.missing_uuid {
        warn!(
            "{} has debug info but no LC_UUID, so it cannot be matched to \
             crash events (skipping). Relink without stripping the UUID load \
             command (ld adds one by default; `-no_uuid` removes it).",
            path.display()
        );
    }

    for path in &report.compressed_dwarf {
        warn!(
            "{} carries compressed DWARF (`__zdebug` sections), which can't be \
             used for symbolication yet (skipping). Go compresses DWARF by \
             default on macOS — rebuild with `-ldflags=-compressdwarf=false` \
             and upload that binary.",
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
        // Only fail the run when there's nothing valid to upload at all;
        // otherwise a stray build-id-less helper binary would block every valid
        // symbol, including any dSYM bundles found alongside it.
        if nothing_to_upload {
            anyhow::bail!("{guidance}");
        }
        warn!("{guidance}");
    }

    if nothing_to_upload {
        anyhow::bail!(
            "No ELF or Mach-O files with debug info or dSYM bundles found in {}",
            directory.display()
        );
    }

    Ok(())
}
