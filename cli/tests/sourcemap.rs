use posthog_cli::sourcemaps::{
    content::SourceMapContent, inject::inject_pairs, plain::inject::is_javascript_file,
    source_pairs::SourcePair,
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
    directory: &PathBuf,
    ignore_globs: &[String],
    prefix: &Option<String>,
) -> Result<Vec<SourcePair>> {
    posthog_cli::sourcemaps::source_pairs::read_pairs(
        directory,
        ignore_globs,
        is_javascript_file,
        prefix,
    )
}

#[test]
fn test_search_without_prefix() {
    let pairs =
        read_pairs(&get_case_path("search"), &Vec::new(), &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 3);
}

#[test]
fn test_search_with_prefix() {
    let pairs = read_pairs(
        &get_case_path("search"),
        &Vec::new(),
        &Some("/static/".to_string()),
    )
    .expect("Failed to read pairs");
    assert_eq!(pairs.len(), 4);
}

#[test]
fn test_ignore() {
    let pairs = read_pairs(&get_case_path(""), &Vec::new(), &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 6);

    let pairs = read_pairs(&get_case_path(""), &["**/search/**".to_string()], &None)
        .expect("Failed to read pairs");
    assert_eq!(pairs.len(), 3);
}

#[test]
fn test_pair_inject() {
    let case_path = get_case_path("inject");
    let mut pairs = read_pairs(&case_path, &Vec::new(), &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .add_chunk_id(chunk_id.to_string())
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
    let mut pairs = read_pairs(&case_path, &Vec::new(), &None).expect("Failed to read pairs");
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .add_chunk_id(chunk_id.to_string())
        .expect("Failed to set chunk ID");

    let bytes = serde_json::to_string(&current_pair.sourcemap.inner.content).unwrap();

    let _ = sourcemap::SourceMap::from_slice(bytes.as_bytes())
        .expect("Failed to parse as a flattened sourcemap");
}

#[test]
fn test_pair_remove() {
    let case_path = get_case_path("inject");
    let mut pairs = read_pairs(&case_path, &Vec::new(), &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .add_chunk_id(chunk_id.to_string())
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
fn test_reinject_without_new_release() {
    let case_path = get_case_path("reinject");
    let pairs = read_pairs(&case_path, &Vec::new(), &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let injected_pairs = inject_pairs(pairs, None).expect("Failed to inject pairs");
    let first_pair = injected_pairs.first().expect("Failed to get first pair");
    assert_ne!(&first_pair.source.get_chunk_id().unwrap(), "0");
    assert_eq!(
        &first_pair.sourcemap.get_chunk_id().unwrap(),
        &first_pair.source.get_chunk_id().unwrap()
    );
    assert!(&first_pair.sourcemap.get_release_id().is_none());
}

#[test]
fn test_reinject_with_new_release() {
    let case_path = get_case_path("reinject");
    let pairs = read_pairs(&case_path, &Vec::new(), &None).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let release_id = uuid::Uuid::now_v7().to_string();
    let injected_pairs =
        inject_pairs(pairs, Some(release_id.clone())).expect("Failed to inject pairs");
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
