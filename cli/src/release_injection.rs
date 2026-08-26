//! Stamp a created release's id into the compiled binary, so the SDK reports it as `$release_id` —
//! the native equivalent of injecting `$release_id` into a web bundle.
//!
//! Language-agnostic: it patches any native binary carrying the marker and no-ops elsewhere, so any
//! SDK that compiles the same marker in is injected the same way. The layout is a shared contract;
//! keep it in sync with the SDKs (posthog-rs `src/release_marker.rs`).

use std::fs;
use std::path::Path;

use anyhow::{bail, Result};
use tracing::{info, warn};
use walkdir::WalkDir;

/// Marks the slot for the byte scan. Long and unusual to avoid a coincidental match.
const MAGIC: &[u8] = b"~posthog-release-id~v1~";
/// The slot holds a 36-byte canonical UUID.
const SLOT_LEN: usize = 36;
/// What the SDK compiles into the slot, and what an un-injected binary reads: the nil UUID.
const PLACEHOLDER: &[u8] = b"00000000-0000-0000-0000-000000000000";

const ELF_MAGIC: &[u8; 4] = b"\x7fELF";
// Thin little-endian/big-endian Mach-O and both fat headers.
const MACHO_MAGICS: [[u8; 4]; 4] = [
    [0xcf, 0xfa, 0xed, 0xfe],
    [0xce, 0xfa, 0xed, 0xfe],
    [0xca, 0xfe, 0xba, 0xbe],
    [0xbe, 0xba, 0xfe, 0xca],
];

/// Overwrite the marker slot with `release_id` in every native binary under `directory` that
/// carries it; returns how many were patched. The overwrite is fixed-width and leaves the build id
/// (Mach-O `LC_UUID`, ELF `.note.gnu.build-id`) untouched, so the uploaded symbols still match.
pub fn inject_release_id(directory: &Path, release_id: &str, resign: bool) -> Result<usize> {
    let id = release_id.as_bytes();
    if id.len() != SLOT_LEN {
        bail!(
            "release id {release_id:?} is {} bytes, expected {SLOT_LEN} (a canonical UUID)",
            id.len()
        );
    }

    let mut patched = 0usize;
    for entry in WalkDir::new(directory).follow_links(true) {
        let entry = match entry {
            Ok(entry) => entry,
            Err(e) => {
                warn!("Skipping unreadable path while scanning for the release marker: {e}");
                continue;
            }
        };
        let path = entry.path();
        if !entry.file_type().is_file() {
            continue;
        }
        // Skip `.dSYM` internals — the executable next to the bundle carries the marker, not its
        // debug companion.
        if path
            .ancestors()
            .any(|p| p.extension().is_some_and(|e| e == "dSYM"))
        {
            continue;
        }
        if !has_native_magic(path) {
            continue;
        }

        let Ok(mut data) = fs::read(path) else {
            continue;
        };
        // A slot that already holds `id` is still written and re-signed below. Cargo hardlinks
        // `target/<profile>/<bin>` to `deps/<bin>-<hash>`, and `codesign` re-signs into a new
        // inode, which splits that link: after the first path is re-signed, its twin still holds
        // the injected bytes with the now-invalid signature. Only a second write and re-sign of
        // the twin — which the walk reaches as a path of its own — makes it runnable again, so
        // "already injected" must never short-circuit into a skip.
        if patch_all_slots(&mut data, id) {
            let macho = is_macho(&data);
            // Check the signature before overwriting the file, so we can tell whether re-signing
            // ad-hoc would strip a real identity.
            let had_real_signature = macho && resign && macho_has_real_signature(path);
            match fs::write(path, &data) {
                Ok(()) => {
                    // Editing a Mach-O invalidates its code signature and macOS won't run it.
                    if macho && resign {
                        if had_real_signature {
                            warn!(
                                "{} was signed with a real identity, which injecting invalidated; \
                                 it was re-signed ad-hoc and is no longer distributable. Inject \
                                 before your signing step, or pass --no-resign and sign after.",
                                path.display()
                            );
                        }
                        resign_macho(path);
                    } else if macho {
                        info!(
                            "Skipped re-signing {} (--no-resign); sign it before running on macOS",
                            path.display()
                        );
                    }
                    info!("Injected release id into {}", path.display());
                    patched += 1;
                }
                Err(e) => warn!(
                    "Found the release marker in {} but could not write it back: {e}",
                    path.display()
                ),
            }
        }
    }
    Ok(patched)
}

/// Byte offsets of every marker slot in `data`: the 36 bytes after each `MAGIC` that still hold
/// a UUID. A coincidental `MAGIC` in unrelated bytes has no UUID after it and is not a slot.
fn slot_offsets(data: &[u8]) -> Vec<usize> {
    let mut offsets = Vec::new();
    let mut from = 0;
    while let Some(rel) = find(&data[from..], MAGIC) {
        let slot_at = from + rel + MAGIC.len();
        from = slot_at;
        if slot_at + SLOT_LEN <= data.len() && looks_like_uuid(&data[slot_at..slot_at + SLOT_LEN]) {
            offsets.push(slot_at);
        }
    }
    offsets
}

/// Overwrite every marker slot in `data` with `id`; returns whether there was a slot to write.
/// A slot that already holds `id` is written again, so the caller still rewrites and re-signs
/// the file.
fn patch_all_slots(data: &mut [u8], id: &[u8]) -> bool {
    let offsets = slot_offsets(data);
    for &at in &offsets {
        data[at..at + SLOT_LEN].copy_from_slice(id);
    }
    !offsets.is_empty()
}

/// Put the placeholder back into every marker slot in `data`, undoing an earlier injection;
/// returns how many slots held an injected id. Symbols go through this before upload, so the
/// symbol set of an unchanged binary is byte-identical across releases: on Linux the marker
/// lives in the same ELF that is uploaded, and an injected id would change its content hash on
/// every release.
pub fn reset_slots(data: &mut [u8]) -> usize {
    let mut reset = 0;
    for at in slot_offsets(data) {
        let slot = &mut data[at..at + SLOT_LEN];
        if slot != PLACEHOLDER {
            slot.copy_from_slice(PLACEHOLDER);
            reset += 1;
        }
    }
    reset
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() || haystack.len() < needle.len() {
        return None;
    }
    haystack.windows(needle.len()).position(|w| w == needle)
}

/// A canonical UUID string: hex digits, with dashes at positions 8, 13, 18, and 23.
fn looks_like_uuid(slot: &[u8]) -> bool {
    slot.len() == SLOT_LEN
        && slot.iter().enumerate().all(|(i, &b)| {
            if matches!(i, 8 | 13 | 18 | 23) {
                b == b'-'
            } else {
                b.is_ascii_hexdigit()
            }
        })
}

fn has_native_magic(path: &Path) -> bool {
    use std::io::Read;
    let Ok(mut file) = fs::File::open(path) else {
        return false;
    };
    let mut magic = [0u8; 4];
    if file.read_exact(&mut magic).is_err() {
        return false;
    }
    &magic == ELF_MAGIC || MACHO_MAGICS.contains(&magic)
}

fn is_macho(data: &[u8]) -> bool {
    data.len() >= 4 && MACHO_MAGICS.contains(&[data[0], data[1], data[2], data[3]])
}

/// Whether the Mach-O at `path` carries a real signing identity (not ad-hoc). `codesign` prints the
/// signature to stderr: an ad-hoc signature says `Signature=adhoc`, a real one has an `Authority=`
/// chain, and an unsigned binary exits non-zero. Only meaningful on macOS.
fn macho_has_real_signature(path: &Path) -> bool {
    if !cfg!(target_os = "macos") {
        return false;
    }
    match std::process::Command::new("codesign")
        .args(["-d", "--verbose=2"])
        .arg(path)
        .output()
    {
        Ok(out) => {
            out.status.success()
                && !String::from_utf8_lossy(&out.stderr).contains("Signature=adhoc")
        }
        Err(_) => false,
    }
}

/// Re-sign a Mach-O ad-hoc after editing, so macOS will run it again. `codesign` only exists on
/// macOS, so anywhere else this warns instead of re-signing: the injection itself succeeded, but
/// the binary needs a signature before it runs on macOS. A missing or failing `codesign` warns
/// rather than fails for the same reason.
fn resign_macho(path: &Path) {
    if !cfg!(target_os = "macos") {
        warn!(
            "{} is a Mach-O whose code signature the injection invalidated, and it cannot be \
             re-signed here (codesign is macOS-only); sign it before it runs on macOS",
            path.display()
        );
        return;
    }
    match std::process::Command::new("codesign")
        .args(["--force", "--sign", "-"])
        .arg(path)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
    {
        Ok(status) if status.success() => {}
        Ok(status) => warn!(
            "codesign exited {status} for {} after injection; the binary may not run until it is \
             re-signed",
            path.display()
        ),
        Err(e) => warn!(
            "could not run codesign for {} after injection ({e}); the binary may not run until it \
             is re-signed",
            path.display()
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const NIL: &[u8] = PLACEHOLDER;
    const REAL: &[u8] = b"0e9b3c7a-5d1f-42a8-b6c4-e2d0f8a17593";

    fn marker(slot: &[u8]) -> Vec<u8> {
        [MAGIC, slot].concat()
    }

    #[test]
    fn patches_the_nil_placeholder_in_place() {
        let mut data = marker(NIL);
        let before = data.len();
        assert!(patch_all_slots(&mut data, REAL));
        assert_eq!(data.len(), before, "the overwrite must not change the size");
        assert_eq!(&data[MAGIC.len()..], REAL);
    }

    #[test]
    fn is_idempotent_over_an_already_injected_slot() {
        // Re-injecting an already-injected binary must still overwrite.
        let mut data = marker(REAL);
        let other = b"11111111-2222-4333-8444-555555555555";
        assert!(patch_all_slots(&mut data, other));
        assert_eq!(&data[MAGIC.len()..], other);
    }

    #[test]
    fn a_slot_that_already_holds_the_id_is_still_reported() {
        // The hardlinked twin of a re-signed Mach-O (cargo's `deps/<bin>-<hash>` and `<bin>`)
        // already carries the id but not a valid signature, and only gets one because the walk
        // writes and re-signs it again. A "nothing changed, skip" shortcut here would leave it
        // unrunnable on macOS.
        let mut data = marker(REAL);
        assert!(patch_all_slots(&mut data, REAL));
        assert_eq!(&data[MAGIC.len()..], REAL);
    }

    #[test]
    fn leaves_a_coincidental_magic_without_a_uuid_slot_alone() {
        let mut data = [MAGIC, b"this is not a uuid, just some text!!!"].concat();
        let original = data.clone();
        assert!(!patch_all_slots(&mut data, REAL));
        assert_eq!(data, original);
    }

    #[test]
    fn patches_every_occurrence() {
        // Two binaries' worth of marker in one buffer (e.g. a workspace) both get the id.
        let mut data = [marker(NIL), vec![0xAA; 8], marker(NIL)].concat();
        assert!(patch_all_slots(&mut data, REAL));
        let count = data.windows(REAL.len()).filter(|w| *w == REAL).count();
        assert_eq!(count, 2);
    }

    #[test]
    fn reset_restores_the_placeholder_in_every_injected_slot() {
        // The symbols of a binary injected twice must upload as if never injected.
        let mut data = [marker(REAL), vec![0xAA; 8], marker(REAL)].concat();
        let pristine = [marker(NIL), vec![0xAA; 8], marker(NIL)].concat();
        assert_eq!(reset_slots(&mut data), 2);
        assert_eq!(data, pristine);
    }

    #[test]
    fn reset_leaves_a_placeholder_and_a_coincidental_magic_alone() {
        // Nothing to undo: the upload of a never-injected binary must be untouched.
        let mut data = [
            marker(NIL),
            [MAGIC, b"this is not a uuid, just some text!!!"].concat(),
        ]
        .concat();
        let original = data.clone();
        assert_eq!(reset_slots(&mut data), 0);
        assert_eq!(data, original);
    }

    #[test]
    fn reset_undoes_a_patch_exactly() {
        let original = marker(NIL);
        let mut data = original.clone();
        assert!(patch_all_slots(&mut data, REAL));
        assert_eq!(reset_slots(&mut data), 1);
        assert_eq!(data, original);
    }

    #[test]
    fn rejects_a_release_id_that_is_not_a_36_byte_uuid() {
        // An empty directory, so nothing is scanned even if the check ever moved after the walk.
        let dir = tempfile::tempdir().unwrap();
        let err = inject_release_id(dir.path(), "too-short", true).unwrap_err();
        assert!(err.to_string().contains("expected 36"));
    }
}
