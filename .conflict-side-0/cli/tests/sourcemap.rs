use posthog_cli::utils::sourcemaps::read_pairs;
use std::{
    fs,
    path::{Path, PathBuf},
};
use test_log::test;

fn get_case_path(relative_path: &str) -> PathBuf {
    PathBuf::from("tests/_cases")
        .join(relative_path)
        .canonicalize()
        .expect("Failed to canonicalize path")
}

fn assert_file_eq(base_path: &Path, path: &str, actual: &str) {
    let expected = fs::read_to_string(base_path.join(path)).expect("Failed to read expected file");
    assert_eq!(expected, actual);
}

#[test]
fn test_search() {
    let pairs = read_pairs(&get_case_path("search"), &Vec::new()).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 2);
}

#[test]
fn test_ignore() {
    let pairs = read_pairs(&get_case_path(""), &Vec::new()).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 4);

    let pairs = read_pairs(&get_case_path(""), &["**/search/**".to_string()])
        .expect("Failed to read pairs");
    assert_eq!(pairs.len(), 2);
}

#[test]
fn test_pair_inject() {
    let case_path = get_case_path("inject");
    let mut pairs = read_pairs(&case_path, &Vec::new()).expect("Failed to read pairs");
    assert_eq!(pairs.len(), 1);
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .set_chunk_id(chunk_id.to_string())
        .expect("Failed to set chunk ID");

    assert_file_eq(
        &case_path,
        "chunk.js.expected",
        &current_pair.source.content,
    );
    assert_file_eq(
        &case_path,
        "chunk.js.map.expected",
        &current_pair.sourcemap.content,
    );
}

#[test]
fn test_index_inject() {
    let case_path = get_case_path("index_map");
    let mut pairs = read_pairs(&case_path, &Vec::new()).expect("Failed to read pairs");
    let current_pair = pairs.first_mut().expect("Failed to get first pair");
    let chunk_id = "00000-00000-00000";
    current_pair
        .set_chunk_id(chunk_id.to_string())
        .expect("Failed to set chunk ID");

    let _ = sourcemap::SourceMap::from_slice(current_pair.sourcemap.content.as_bytes())
        .expect("Failed to parse as a flattened sourcemap");
}
