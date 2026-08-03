use posthog_cli::{
    sourcemaps::{
        content::{MinifiedSourceFile, SourceMapContent, SourceMapFile},
        inject::{inject_pairs, inject_pairs_legacy},
        plain::inject::is_javascript_file,
        source_pairs::SourcePair,
    },
    utils::files::{FileSelection, SourceFile},
};

use anyhow::Result;
use serde_json::json;

use std::{
    fs,
    path::{Path, PathBuf},
};
use test_log::test;

macro_rules! case {
    ($relative_path:expr) => {
        concat!("_cases/", $relative_path)
    };
}

fn get_case_path(relative_path: &str) -> PathBuf {
    PathBuf::from("tests/_cases")
        .join(relative_path)
        .canonicalize()
        .expect("Failed to canonicalize path")
}

fn assert_file_eq(base_path: &Path, path: &str, actual: impl Into<String>) {
    let expected = fs::read_to_string(base_path.join(path)).expect("Failed to read expected file");
    assert_eq!(expected, actual.into());
}

pub fn read_pairs(
    directories: Vec<PathBuf>,
    exclude: Vec<String>,
    include: Vec<String>,
    prefix: &Option<String>,
) -> Result<Vec<SourcePair>> {
    let selection = FileSelection::from_roots(directories)
        .include(include)?
        .exclude(exclude)?;

    Ok(posthog_cli::sourcemaps::source_pairs::read_pairs(
        selection.into_iter().filter(is_javascript_file),
        prefix,
    ))
}

#[test]
fn test_search_without_multiple_files() {
    let pairs = read_pairs(
        vec![
            get_case_path("search/index.js"),
            get_case_path("search/assets/chunk.min.js"),
        ],
        vec![],
        vec![],
        &None,
    )
    .expect("Failed to read pairs");
    assert_eq!(pairs.len(), 2);
}

#[test]
fn test_search_without_prefix() {
    let pairs = read_pairs(vec![get_case_path("search")], vec![], vec![], &None)
        .expect("Failed to read pairs");
    assert_eq!(pairs.len(), 3);
}

#[test]
fn test_search_with_prefix() {
    let pairs = read_pairs(
        vec![get_case_path("search")],
        vec![],
        vec![],
        &Some("/static/".to_string()),
    )
    .expect("Failed to read pairs");
    assert_eq!(pairs.len(), 4);
}

#[test]
fn test_include() {
    let pairs = read_pairs(
        vec![get_case_path("search")],
        vec![],
        vec!["**/index.js".to_string()],
        &None,
    )
    .expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    assert_eq!(
        pairs.first().unwrap().source.inner.path,
        get_case_path("search/index.js")
    );
}

#[test]
fn test_exclude() {
    let pairs = read_pairs(
        vec![get_case_path("")],
        vec!["**/search/**".to_string()],
        vec![],
        &None,
    )
    .expect("Failed to read pairs");
    assert_eq!(pairs.len(), 5);
    assert!(pairs
        .iter()
        .map(|pair| &pair.source.inner.path)
        .any(|path| path == &get_case_path("inject/chunk.js")));

    // Make sure chunks are ignored
    assert!(!pairs
        .iter()
        .map(|pair| &pair.source.inner.path)
        .any(|path| path.to_string_lossy().contains("search/")));
}

#[test]
fn test_pair_inject() {
    let case_path = get_case_path("inject");
    let mut pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .add_chunk_id(chunk_id.to_string(), None)
        .expect("Failed to set chunk ID");

    assert_file_eq(
        &case_path,
        "chunk.js.expected",
        &current_pair.source.inner.content,
    );

    let expected_val: SourceMapContent =
        serde_json::from_str(include_str!(case!("inject/chunk.js.map.expected"))).unwrap();

    assert_eq!(expected_val, current_pair.sourcemap.inner.content);
}

#[test]
fn test_index_inject() {
    let case_path = get_case_path("index_map");
    let mut pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .add_chunk_id(chunk_id.to_string(), None)
        .expect("Failed to set chunk ID");

    let bytes = serde_json::to_string(&current_pair.sourcemap.inner.content).unwrap();

    let _ = sourcemap::SourceMap::from_slice(bytes.as_bytes())
        .expect("Failed to parse as a flattened sourcemap");
}

#[test]
fn test_index_inject_retains_extension_fields() {
    let case_path = get_case_path("index_map_with_extension");
    let mut pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    let current_pair = pairs.first_mut().expect("Failed to get first pair");

    assert!(current_pair
        .sourcemap
        .inner
        .content
        .fields
        .contains_key("x_custom_extension_field"));

    let chunk_id = "00000-00000-00000";
    current_pair
        .add_chunk_id(chunk_id.to_string(), None)
        .expect("Failed to set chunk ID");

    // Extension field should be retained after flattening
    assert!(
        current_pair
            .sourcemap
            .inner
            .content
            .fields
            .contains_key("x_custom_extension_field"),
        "Extension field should be retained after flattening index map"
    );

    // Should still be parseable as a valid flattened sourcemap
    let bytes = serde_json::to_string(&current_pair.sourcemap.inner.content).unwrap();
    let _ = sourcemap::SourceMap::from_slice(bytes.as_bytes())
        .expect("Failed to parse as a flattened sourcemap");
}

#[test]
fn test_pair_remove() {
    let case_path = get_case_path("inject");
    let mut pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .add_chunk_id(chunk_id.to_string(), None)
        .expect("Failed to set chunk ID");

    current_pair
        .remove_chunk_id(chunk_id.to_string())
        .expect("Failed to remove chunk ID");

    assert_file_eq(&case_path, "chunk.js", &current_pair.source.inner.content);

    let expected_val: SourceMapContent =
        serde_json::from_str(include_str!(case!("inject/chunk.js.map"))).unwrap();

    assert_eq!(expected_val, current_pair.sourcemap.inner.content,);
}

#[test]
fn test_reinject_is_idempotent() {
    // A chunk that already carries a content-addressed id must survive re-injection untouched.
    // Regenerating the id on every build would orphan the already-uploaded symbol set.
    let case_path = get_case_path("reinject");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let source_before = pairs.first().unwrap().source.inner.content.clone();

    let injected_pairs = inject_pairs(pairs, None).expect("Failed to inject pairs");
    let first_pair = injected_pairs.first().expect("Failed to get first pair");

    assert_eq!(first_pair.source.get_chunk_id().as_deref(), Some("0"));
    assert_eq!(first_pair.source.inner.content, source_before);
}

#[test]
fn test_inject_with_release_embeds_id_in_source() {
    // Injecting with a release must embed its id into the JS chunk itself — that global is the
    // SDK's only source of the release — and must leave the release out of the sourcemap, so
    // nothing binds the uploaded symbol set to it. The SDK ignores the global unless it is a
    // non-empty string, so it has to be emitted as a quoted string literal.
    let case_path = get_case_path("inject");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let release_id = "0199f7c2-1c4e-7c3a-9f8b-2d6e4a1b7c05";

    let injected_pairs = inject_pairs(pairs, Some(release_id)).expect("Failed to inject pairs");
    let first_pair = injected_pairs.first().expect("Failed to get first pair");

    let source = &first_pair.source.inner.content;
    assert!(
        source.contains(&format!(r#"_posthogReleaseId||"{release_id}""#)),
        "source: {source}"
    );
    assert!(first_pair.source.get_chunk_id().is_some());
    assert!(first_pair.sourcemap.get_release_id().is_none());
}

#[test]
fn test_legacy_reinject_without_new_release() {
    // Legacy path: with no release, an existing chunk carrying a stale release id is regenerated
    // and the release id is cleared from the sourcemap.
    let case_path = get_case_path("reinject");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let injected_pairs = inject_pairs_legacy(pairs, None).expect("Failed to inject pairs");
    let first_pair = injected_pairs.first().expect("Failed to get first pair");
    assert_ne!(&first_pair.source.get_chunk_id().unwrap(), "0");
    assert_eq!(
        &first_pair.sourcemap.get_chunk_id().unwrap(),
        &first_pair.source.get_chunk_id().unwrap()
    );
    assert!(&first_pair.sourcemap.get_release_id().is_none());
}

#[test]
fn test_legacy_reinject_with_new_release() {
    // Legacy path: a new release id regenerates the chunk id and is stamped into the sourcemap.
    let case_path = get_case_path("reinject");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let release_id = uuid::Uuid::now_v7().to_string();
    let injected_pairs =
        inject_pairs_legacy(pairs, Some(release_id.clone())).expect("Failed to inject pairs");
    let first_pair = injected_pairs.first().expect("Failed to get first pair");
    assert_ne!(&first_pair.source.get_chunk_id().unwrap(), "0");
    assert_eq!(
        &first_pair.sourcemap.get_chunk_id().unwrap(),
        &first_pair.source.get_chunk_id().unwrap()
    );
    assert_eq!(
        first_pair.sourcemap.get_release_id().unwrap(),
        release_id.clone()
    );
}

#[test]
fn test_upload_set() {
    let case_path = get_case_path("search");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");

    // Find pairs where source and sourcemap have different chunk IDs
    let pair_with_different_ids = pairs
        .into_iter()
        .find(|p| {
            let source_chunk_id = p.source.get_chunk_id();
            let sourcemap_chunk_id = p.sourcemap.get_chunk_id();

            source_chunk_id.is_some()
                && sourcemap_chunk_id.is_some()
                && source_chunk_id != sourcemap_chunk_id
        })
        .expect("Should find at least one pair with different chunk IDs");

    let source_chunk_id = pair_with_different_ids.source.get_chunk_id().unwrap();
    let sourcemap_chunk_id = pair_with_different_ids.sourcemap.get_chunk_id().unwrap();

    // Verify they are different
    assert_ne!(source_chunk_id, sourcemap_chunk_id);

    // Convert to UploadSet
    use posthog_cli::api::symbol_sets::SymbolSetUpload;
    let upload_set: SymbolSetUpload = pair_with_different_ids
        .try_into()
        .expect("Failed to convert to SymbolSetUpload");

    // Verify that the upload set uses the source's chunk ID, not the sourcemap's
    assert_eq!(upload_set.chunk_id, source_chunk_id);
    assert_ne!(upload_set.chunk_id, sourcemap_chunk_id);
}

const BUNDLER_DEBUG_ID: &str = "11111111-2222-4333-8444-555555555555";

fn make_pair(source_content: &str, map_json: serde_json::Value) -> SourcePair {
    SourcePair {
        source: MinifiedSourceFile {
            inner: SourceFile::new(PathBuf::from("chunk.js"), source_content.to_string()),
        },
        sourcemap: SourceMapFile {
            inner: SourceFile::new(
                PathBuf::from("chunk.js.map"),
                serde_json::from_value(map_json).expect("Failed to build SourceMapContent"),
            ),
        },
    }
}

fn map_with_debug_id(debug_id: Option<&str>) -> serde_json::Value {
    let mut map = json!({
        "version": 3,
        "file": "chunk.js",
        "sources": ["src/index.js"],
        "sourcesContent": ["console.log(1)\n"],
        "names": [],
        "mappings": "AAAA",
    });
    if let Some(debug_id) = debug_id {
        map["debugId"] = json!(debug_id);
    }
    map
}

#[test]
fn test_inject_adopts_bundler_debug_id() {
    // The bundler already stamped a debug id into the chunk and its map. Inject must adopt it
    // as the chunk id and still apply the mapping adjustment for the prepended snippet — the
    // old `alias = "debugId"` conflation made the map look already-processed and skipped it.
    let pair = make_pair(
        &format!(
            "console.log(1);\n//# debugId={BUNDLER_DEBUG_ID}\n//# sourceMappingURL=chunk.js.map\n"
        ),
        map_with_debug_id(Some(BUNDLER_DEBUG_ID)),
    );

    let injected = inject_pairs(vec![pair], None).expect("Failed to inject pairs");
    let pair = injected.first().unwrap();

    assert_eq!(
        pair.source.get_chunk_id().as_deref(),
        Some(BUNDLER_DEBUG_ID)
    );
    assert!(pair
        .source
        .inner
        .content
        .contains(&format!("=\"{BUNDLER_DEBUG_ID}\"")));
    let map = &pair.sourcemap.inner.content;
    assert_eq!(map.chunk_id.as_deref(), Some(BUNDLER_DEBUG_ID));
    assert_eq!(map.debug_id.as_deref(), Some(BUNDLER_DEBUG_ID));
    assert_ne!(
        map.fields.get("mappings").and_then(|v| v.as_str()),
        Some("AAAA"),
        "mapping adjustment for the prepended snippet was not applied"
    );
}

#[test]
fn test_inject_ignores_malformed_debug_id() {
    // Adopted ids flow into upload rows and SDK events; a bundler emitting a non-UUID debug id
    // must not poison them — fall back to the content-derived chunk id.
    let pair = make_pair(
        "console.log(1);\n//# debugId=not-a-uuid\n//# sourceMappingURL=chunk.js.map\n",
        map_with_debug_id(None),
    );

    let injected = inject_pairs(vec![pair], None).expect("Failed to inject pairs");
    let chunk_id = injected.first().unwrap().source.get_chunk_id().unwrap();

    assert_ne!(chunk_id, "not-a-uuid");
    assert!(uuid::Uuid::parse_str(&chunk_id).is_ok());
}

#[test]
fn test_inject_prefers_chunk_debug_id_over_sourcemap() {
    // Sourcemaps can be shared across chunks, so the chunk's own debug id must win when the two
    // disagree — flipping the precedence would stamp one chunk's id onto its siblings.
    let map_debug_id = "99999999-8888-4777-8666-555555555555";
    let pair = make_pair(
        &format!(
            "console.log(1);\n//# debugId={BUNDLER_DEBUG_ID}\n//# sourceMappingURL=chunk.js.map\n"
        ),
        map_with_debug_id(Some(map_debug_id)),
    );

    let injected = inject_pairs(vec![pair], None).expect("Failed to inject pairs");
    let pair = injected.first().unwrap();

    assert_eq!(
        pair.source.get_chunk_id().as_deref(),
        Some(BUNDLER_DEBUG_ID)
    );
    assert_eq!(
        pair.sourcemap.inner.content.debug_id.as_deref(),
        Some(map_debug_id),
        "the map's own debugId field must be preserved, not overwritten"
    );
}

#[test]
fn test_file_selection() {
    // This does not work with glob patterns
    let res = read_pairs(
        vec![get_case_path("paths")],
        vec![],
        vec!["**/chunks/app/[locale]/(app)/[...not-found]/index.js".to_string()],
        &None,
    );
    assert!(res.is_err());
    assert_eq!(res.unwrap_err().to_string(), "error parsing glob '**/chunks/app/[locale]/(app)/[...not-found]/index.js': invalid range; 't' > 'f'");

    // But should work with file paths
    let res = read_pairs(
        vec![get_case_path(
            "paths/chunks/app/[locale]/(app)/[...not-found]/index.js",
        )],
        vec![],
        vec![],
        &None,
    );
    assert!(res.is_ok());
}
