use hogvm::hog_stl;

pub fn main() {
    let output_file = std::env::args()
        .next_back()
        .expect("Usage: stl_dump <output_file>");
    println!("Writing to {output_file}");
    let res = format!(
        "RUST_HOGVM_STL = [\n  {}\n]",
        hogvm::stl()
            .iter()
            .map(|(name, _)| name.as_str())
            .chain(hog_stl().functions().keys().map(|name| name.as_str()))
            .map(|n| format!("\"{n}\""))
            .collect::<Vec<_>>()
            .join(",\n  ")
    );
    std::fs::write(output_file, res.as_bytes()).expect("Failed to write output file");
}
