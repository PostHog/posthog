use posthog_cli::{
    sourcemaps::{
        args::ReleaseMode,
        content::SourceMapContent,
        inject::{
            inject_pairs, inject_pairs_legacy, inject_pairs_legacy_with_options,
        },
        plain::inject::{is_javascript_file, is_stylesheet_file},
        source_pairs::SourcePair,
    },
    utils::files::FileSelection,
};

use anyhow::Result;

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
fn test_stylesheet_pair_is_discoverable_for_cleanup() {
    let dir = tempfile::tempdir().expect("Failed to create stylesheet fixture directory");
    let stylesheet_path = dir.path().join("app.css");
    fs::write(
        &stylesheet_path,
        ".app { color: black; }\n/*# sourceMappingURL=app.css.map*/\n",
    )
    .expect("Failed to write stylesheet fixture");
    fs::write(
        dir.path().join("app.css.map"),
        r#"{"version":3,"sources":[],"names":[],"mappings":""}"#,
    )
    .expect("Failed to write stylesheet sourcemap fixture");

    let selection = FileSelection::from_roots(vec![dir.path().to_path_buf()])
        .include(vec![])
        .expect("Failed to select stylesheet fixture");
    let pairs = posthog_cli::sourcemaps::source_pairs::read_pairs(
        selection.into_iter().filter(is_stylesheet_file),
        &None,
    );

    assert_eq!(pairs.len(), 1);
    assert_eq!(
        pairs[0].source.inner.path,
        stylesheet_path
            .canonicalize()
            .expect("Failed to canonicalize stylesheet fixture")
    );
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
fn test_pair_remove_strips_release_variant_snippet() {
    // Removal must strip the release-carrying snippet too, or updating a chunk would stack
    // a second snippet on top of the old one.
    let case_path = get_case_path("inject");
    let mut pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .add_chunk_id(
            chunk_id.to_string(),
            Some("0199f7c2-1c4e-7c3a-9f8b-2d6e4a1b7c05"),
        )
        .expect("Failed to set chunk ID");

    current_pair
        .remove_chunk_id(chunk_id.to_string())
        .expect("Failed to remove chunk ID");

    assert_file_eq(&case_path, "chunk.js", &current_pair.source.inner.content);

    let expected_val: SourceMapContent =
        serde_json::from_str(include_str!(case!("inject/chunk.js.map"))).unwrap();
    assert_eq!(expected_val, current_pair.sourcemap.inner.content);
}

#[test]
fn test_reinject_refreshes_stale_release_id() {
    // Re-running inject over an already-injected dist with a new release must swap the
    // embedded release id while keeping the content-addressed chunk id.
    let case_path = get_case_path("inject");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    let injected = inject_pairs(pairs, Some("release-a")).expect("Failed to inject pairs");
    let chunk_id = injected
        .first()
        .and_then(|p| p.get_chunk_id())
        .expect("chunk id");

    let refreshed = inject_pairs(injected, Some("release-b")).expect("Failed to re-inject pairs");
    let pair = refreshed.first().expect("Failed to get first pair");

    assert_eq!(pair.get_chunk_id().as_deref(), Some(chunk_id.as_str()));
    let source = &pair.source.inner.content;
    assert!(
        source.contains(r#"_posthogReleaseId||"release-b""#),
        "source: {source}"
    );
    assert!(!source.contains("release-a"), "source: {source}");
}

#[test]
fn test_reinject_without_release_keeps_embedded_release_id() {
    // A run that can't resolve a release has no information — it must not clear the
    // release id a previous run embedded.
    let case_path = get_case_path("inject");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    let injected = inject_pairs(pairs, Some("release-a")).expect("Failed to inject pairs");
    let source_before = injected.first().unwrap().source.inner.content.clone();

    let reinjected = inject_pairs(injected, None).expect("Failed to re-inject pairs");

    assert_eq!(
        reinjected.first().unwrap().source.inner.content,
        source_before
    );
}

#[test]
fn test_reinject_adds_release_to_releaseless_chunk() {
    // A chunk injected while no release was resolvable must pick the release up on a later
    // run, keeping its content-addressed chunk id.
    let case_path = get_case_path("inject");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    let injected = inject_pairs(pairs, None).expect("Failed to inject pairs");
    let chunk_id = injected
        .first()
        .and_then(|p| p.get_chunk_id())
        .expect("chunk id");

    let refreshed = inject_pairs(injected, Some("release-a")).expect("Failed to re-inject pairs");
    let pair = refreshed.first().expect("Failed to get first pair");

    assert_eq!(pair.get_chunk_id().as_deref(), Some(chunk_id.as_str()));
    assert!(pair
        .source
        .inner
        .content
        .contains(r#"_posthogReleaseId||"release-a""#));
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
fn test_preserve_sources_leaves_minified_js_bytes_unchanged() {
    // #86046: Angular ngsw / SRI hash deploy artifacts. Inject must be able to stamp
    // chunk ids without rewriting the minified JS that was just hashed.
    let case_path = get_case_path("inject");
    let pairs =
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let original_source = pairs[0].source.inner.content.clone();

    let release_id = uuid::Uuid::now_v7().to_string();
    let injected = inject_pairs_legacy_with_options(pairs, Some(release_id.clone()), true)
        .expect("Failed to inject pairs with preserve_sources");
    let pair = injected.first().expect("pair");

    assert_eq!(
        pair.source.inner.content, original_source,
        "minified source must remain byte-identical"
    );
    assert!(
        pair.source.get_chunk_id().is_none(),
        "source must not gain a //# chunkId= comment"
    );
    assert_eq!(pair.get_chunk_id().as_deref(), pair.sourcemap.get_chunk_id().as_deref());
    assert!(pair.sourcemap.get_chunk_id().is_some());
    assert_eq!(pair.sourcemap.get_release_id().as_deref(), Some(release_id.as_str()));
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
    let upload_set = pair_with_different_ids
        .into_upload(ReleaseMode::SymbolSet)
        .expect("Failed to convert to SymbolSetUpload");

    // Verify that the upload set uses the source's chunk ID, not the sourcemap's
    assert_eq!(upload_set.chunk_id, source_chunk_id);
    assert_ne!(upload_set.chunk_id, sourcemap_chunk_id);
    // Symbol-set uploads must not precompute a hash: the server stores raw-payload hashes
    // for previously uploaded chunks, and a different hash form would flag every unchanged
    // chunk as a content conflict.
    assert!(upload_set.content_hash.is_none());
}

#[test]
fn test_event_mode_content_hash_is_stable_across_release_states() {
    // The hash must not depend on which snippet variant is embedded. A chunk injected while
    // no release was resolvable, the same chunk injected with a release, and the transition
    // between the two all keep one chunk id, so they must hash identically or the server
    // rejects the later upload as a content_hash_mismatch.
    let case_path = get_case_path("inject");
    let load = || {
        read_pairs(vec![case_path.clone()], vec![], vec![], &None).expect("Failed to read pairs")
    };
    let hash_of = |pairs: Vec<SourcePair>| -> String {
        pairs
            .into_iter()
            .next()
            .expect("Failed to get first pair")
            .into_upload(ReleaseMode::Event)
            .expect("Failed to convert to SymbolSetUpload")
            .content_hash
            .expect("event mode always sets a content hash")
    };

    let releaseless = hash_of(inject_pairs(load(), None).expect("Failed to inject pairs"));
    let with_release = hash_of(
        inject_pairs(load(), Some("11111111-2222-4333-8444-555555555555"))
            .expect("Failed to inject pairs"),
    );
    let transitioned = {
        let injected = inject_pairs(load(), None).expect("Failed to inject pairs");
        hash_of(
            inject_pairs(injected, Some("99999999-8888-4777-8666-000000000000"))
                .expect("Failed to re-inject pairs"),
        )
    };

    assert_eq!(releaseless, with_release);
    assert_eq!(releaseless, transitioned);
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
