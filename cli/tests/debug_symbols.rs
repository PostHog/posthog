use std::io::Read;
use std::path::{Path, PathBuf};

use posthog_cli::api::symbol_sets::SymbolSetUpload;
use posthog_cli::debug_symbols::{
    dedup_uploads_by_chunk_id, discover, elf_debug_id, package_dsym_bundles, report_problems,
};
use posthog_symbol_data::{read_symbol_data, AppleDsym, ElfDebugInfo};

/// The native ELF fixtures shared with cymbal's symbolication tests; built by
/// tests/static/native/build.sh, with debug ids derived the same way cymbal
/// derives them when resolving frames.
fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../rust/cymbal/tests/static/native")
}

/// The Apple dSYM fixtures shared with cymbal's symbolication tests.
fn apple_fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../rust/cymbal/tests/static/apple")
}

/// `dwarfdump` ships with Xcode and only exists on macOS; the dSYM packaging
/// path shells out to it, so tests that exercise real bundles gate on this.
/// Require a *successful* exit, not just a spawn: on macOS `/usr/bin/dwarfdump`
/// is an `xcrun` shim that runs but exits non-zero when the Command Line Tools
/// aren't installed, and that would let the test run without a working tool.
fn dwarfdump_available() -> bool {
    std::process::Command::new("dwarfdump")
        .arg("--version")
        .output()
        .is_ok_and(|out| out.status.success())
}

fn copy_dir_all(src: &Path, dst: &Path) {
    std::fs::create_dir_all(dst).unwrap();
    for entry in std::fs::read_dir(src).unwrap() {
        let entry = entry.unwrap();
        let to = dst.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_dir_all(&entry.path(), &to);
        } else {
            std::fs::copy(entry.path(), &to).unwrap();
        }
    }
}

/// Read the 4-byte magic of the `dwarf` entry inside a symbol_data ZIP payload.
fn dwarf_magic(inner_zip: &[u8]) -> [u8; 4] {
    let mut zip = zip::ZipArchive::new(std::io::Cursor::new(inner_zip.to_vec())).unwrap();
    let mut dwarf = zip.by_name("dwarf").unwrap();
    let mut magic = [0u8; 4];
    dwarf.read_exact(&mut magic).unwrap();
    magic
}

#[test]
fn extracts_debug_ids_matching_cymbal_fixtures() {
    let dir = fixtures_dir();

    assert_eq!(
        elf_debug_id(&dir.join("test_binary_nopie")).unwrap(),
        "7561847b-1054-7eb3-7763-4415adfaa134"
    );
    assert_eq!(
        elf_debug_id(&dir.join("test_binary_pie")).unwrap(),
        "850c70a2-6592-a70c-3e49-c0e443794d23"
    );
    assert_eq!(
        elf_debug_id(&dir.join("test_binary_inline")).unwrap(),
        "140ab543-c098-09dc-22b6-11f72e46d6fe"
    );
}

#[test]
fn discovers_and_packages_elf_files() {
    let report = discover(&fixtures_dir()).unwrap();

    // The three uncompressed ELF fixtures are found and valid
    let mut debug_ids: Vec<&str> = report.files.iter().map(|f| f.debug_id.as_str()).collect();
    debug_ids.sort();
    assert_eq!(
        debug_ids,
        vec![
            "140ab543-c098-09dc-22b6-11f72e46d6fe",
            "7561847b-1054-7eb3-7763-4415adfaa134",
            "850c70a2-6592-a70c-3e49-c0e443794d23",
        ]
    );
    // The classification fixtures in the same directory triage instead
    assert_eq!(report.without_debug_info.len(), 1);
    assert_eq!(report.missing_build_id.len(), 1);
    assert!(report.dsym_bundles.is_empty());

    // Packaged uploads round-trip through the symbol_data container with the
    // binary stored as `dwarf` at the ZIP root — the layout cymbal parses.
    let file = report
        .files
        .into_iter()
        .find(|f| f.debug_id == "850c70a2-6592-a70c-3e49-c0e443794d23")
        .unwrap();
    let upload = file.into_upload(None, false).unwrap();
    assert_eq!(upload.chunk_id, "850c70a2-6592-a70c-3e49-c0e443794d23");

    let unwrapped: ElfDebugInfo = read_symbol_data(&upload.data).unwrap();
    let mut zip = zip::ZipArchive::new(std::io::Cursor::new(unwrapped.data)).unwrap();
    let mut dwarf = zip.by_name("dwarf").unwrap();
    let mut magic = [0u8; 4];
    dwarf.read_exact(&mut magic).unwrap();
    assert_eq!(&magic, b"\x7fELF");
}

#[test]
fn skips_non_elf_and_flags_dsyms() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("readme.txt"), "not an elf").unwrap();
    std::fs::create_dir_all(dir.path().join("MyApp.app.dSYM/Contents")).unwrap();
    std::fs::write(dir.path().join("split.dwp"), b"\x7fELFfake").unwrap();

    let report = discover(dir.path()).unwrap();
    assert!(report.files.is_empty());
    assert_eq!(report.dsym_bundles.len(), 1);
    assert_eq!(report.split_dwarf.len(), 1);
}

#[test]
fn classifies_elfs_without_debug_info_or_build_id() {
    let dir = tempfile::tempdir().unwrap();
    let fixtures = fixtures_dir();
    std::fs::copy(
        fixtures.join("test_binary_nodebug"),
        dir.path().join("test_binary_nodebug"),
    )
    .unwrap();
    std::fs::copy(
        fixtures.join("test_binary_nobuildid"),
        dir.path().join("test_binary_nobuildid"),
    )
    .unwrap();

    let report = discover(dir.path()).unwrap();
    assert!(report.files.is_empty());
    assert_eq!(report.without_debug_info.len(), 1);
    assert_eq!(report.missing_build_id.len(), 1);

    // With nothing uploadable, the missing build id is a hard error
    // carrying linker guidance.
    let err = posthog_cli::debug_symbols::report_problems(&report, dir.path()).unwrap_err();
    assert!(err.to_string().contains("build id"), "got: {err}");

    // A valid ELF alongside turns the hard error into a warning-only run.
    std::fs::copy(
        fixtures.join("test_binary_pie"),
        dir.path().join("test_binary_pie"),
    )
    .unwrap();
    let report = discover(dir.path()).unwrap();
    assert_eq!(report.files.len(), 1);
    assert!(posthog_cli::debug_symbols::report_problems(&report, dir.path()).is_ok());
}

#[test]
fn dsym_only_directory_is_uploadable() {
    // A directory with only a dSYM bundle (no ELF) used to be a hard error
    // pointing at `dsym upload`; `symbol-sets upload` now packages dSYMs itself,
    // so reporting should succeed without that guidance.
    let dir = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(dir.path().join("MyApp.app.dSYM/Contents/Resources/DWARF")).unwrap();

    let report = discover(dir.path()).unwrap();
    assert!(report.files.is_empty());
    assert_eq!(report.dsym_bundles.len(), 1);
    assert!(report_problems(&report, dir.path()).is_ok());
}

#[test]
fn empty_directory_errors_on_both_formats() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("notes.txt"), "nothing to see").unwrap();

    let report = discover(dir.path()).unwrap();
    let err = report_problems(&report, dir.path()).unwrap_err();
    assert!(
        err.to_string()
            .contains("No ELF files with debug info or dSYM bundles"),
        "got: {err}"
    );
}

#[test]
fn dedup_preserves_per_format_chunk_id_casing() {
    // ELF chunk_ids are lowercase, Mach-O dSYM chunk_ids uppercase. The SAME uuid
    // in both cases must NOT be merged — the SDK matches case-sensitively, per
    // format — while an exact duplicate (one uuid found in two bundles) coalesces
    // to the first occurrence.
    let lower = "77c2f55f-c959-487a-9601-6a715a9bb5de";
    let upper = "77C2F55F-C959-487A-9601-6A715A9BB5DE";
    let mk = |chunk_id: &str, data: &[u8]| SymbolSetUpload {
        chunk_id: chunk_id.to_string(),
        release_id: None,
        data: data.to_vec(),
    };

    let deduped = dedup_uploads_by_chunk_id(vec![
        mk(lower, b"elf"),
        mk(upper, b"dsym-bundle-a"),
        mk(upper, b"dsym-bundle-b"),
    ]);

    assert_eq!(
        deduped.len(),
        2,
        "case-distinct ids stay separate; only the exact-duplicate uppercase id merges"
    );
    let ids: Vec<&str> = deduped.iter().map(|u| u.chunk_id.as_str()).collect();
    assert!(
        ids.contains(&lower),
        "lowercase ELF id must survive unchanged"
    );
    assert!(
        ids.contains(&upper),
        "uppercase dSYM id must survive unchanged"
    );
    let kept_upper = deduped.iter().find(|u| u.chunk_id == upper).unwrap();
    assert_eq!(
        kept_upper.data, b"dsym-bundle-a",
        "dedup keeps the first occurrence"
    );
}

#[test]
fn packages_elf_and_dsym_from_one_directory() {
    // The dSYM half shells out to `dwarfdump` (Xcode, macOS-only); on Linux CI
    // it's absent, so skip there. The ELF-only path is covered by the tests above.
    if !dwarfdump_available() {
        eprintln!("skipping packages_elf_and_dsym_from_one_directory: dwarfdump unavailable");
        return;
    }

    let dir = tempfile::tempdir().unwrap();
    std::fs::copy(
        fixtures_dir().join("test_binary_pie"),
        dir.path().join("test_binary_pie"),
    )
    .unwrap();
    copy_dir_all(
        &apple_fixtures_dir().join("test_binary.dSYM"),
        &dir.path().join("test_binary.dSYM"),
    );

    let report = discover(dir.path()).unwrap();
    assert_eq!(report.files.len(), 1, "one ELF discovered");
    assert_eq!(report.dsym_bundles.len(), 1, "one dSYM bundle discovered");
    assert!(report_problems(&report, dir.path()).is_ok());

    // Mirror the upload flow: package ELF + dSYM, then dedup across both formats.
    let mut uploads: Vec<SymbolSetUpload> = report
        .files
        .into_iter()
        .map(|f| f.into_upload(None, false).unwrap())
        .collect();
    uploads.extend(package_dsym_bundles(&report.dsym_bundles, false));
    let uploads = dedup_uploads_by_chunk_id(uploads);
    assert_eq!(uploads.len(), 2, "one ELF + one dSYM upload");

    // ELF: lowercase chunk_id, ElfDebugInfo container, ELF binary inside.
    let elf = uploads
        .iter()
        .find(|u| u.chunk_id == "850c70a2-6592-a70c-3e49-c0e443794d23")
        .expect("ELF upload present with lowercase debug id");
    let elf_inner: ElfDebugInfo = read_symbol_data(&elf.data).unwrap();
    assert_eq!(&dwarf_magic(&elf_inner.data), b"\x7fELF");

    // dSYM: UPPERCASE chunk_id, AppleDsym container, Mach-O binary inside.
    let dsym = uploads
        .iter()
        .find(|u| u.chunk_id == "77C2F55F-C959-487A-9601-6A715A9BB5DE")
        .expect("dSYM upload present with uppercase UUID");
    let dsym_inner: AppleDsym = read_symbol_data(&dsym.data).unwrap();
    assert_ne!(
        &dwarf_magic(&dsym_inner.data),
        b"\x7fELF",
        "dSYM dwarf entry must be a Mach-O binary, not ELF"
    );
}
