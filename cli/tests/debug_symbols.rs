use std::io::Read;
use std::path::{Path, PathBuf};

use posthog_cli::debug_symbols::{discover, elf_debug_id};
use posthog_symbol_data::{read_symbol_data, ElfDebugInfo};

/// The native ELF fixtures shared with cymbal's symbolication tests; built by
/// tests/static/native/build.sh, with debug ids derived the same way cymbal
/// derives them when resolving frames.
fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../rust/cymbal/tests/static/native")
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
