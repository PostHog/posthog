use posthog_symbol_data::{read_symbol_data, write_symbol_data, SourceAndMap};

#[test]
fn test_source_and_map_reading() {
    let input = include_bytes!("static/sourcemap_with_nulls.jsdata").to_vec();
    read_symbol_data::<SourceAndMap>(input).unwrap();
}

#[test]
fn test_inout() {
    let input = SourceAndMap {
        minified_source: "minified_source".to_string(),
        sourcemap: "sourcemap".to_string(),
    };

    let bytes = write_symbol_data(input.clone()).unwrap();
    let output = read_symbol_data::<SourceAndMap>(bytes).unwrap();

    assert_eq!(input, output);
}
