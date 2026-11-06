#![allow(clippy::duplicate_mod)]

pub mod integration_utils;
pub mod utils;

/// Compress raw bytes using the given encoding.
/// Shared across integration tests to avoid duplicating compression logic.
#[allow(dead_code)]
pub fn compress(data: &[u8], encoding: &str) -> Vec<u8> {
    use std::io::Write;
    match encoding {
        "gzip" => {
            let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::fast());
            enc.write_all(data).unwrap();
            enc.finish().unwrap()
        }
        "deflate" => {
            let mut enc =
                flate2::write::DeflateEncoder::new(Vec::new(), flate2::Compression::fast());
            enc.write_all(data).unwrap();
            enc.finish().unwrap()
        }
        "br" => {
            let mut out = Vec::new();
            brotli::BrotliCompress(
                &mut std::io::Cursor::new(data),
                &mut out,
                &brotli::enc::BrotliEncoderParams::default(),
            )
            .unwrap();
            out
        }
        "zstd" => zstd::encode_all(std::io::Cursor::new(data), 1).unwrap(),
        other => panic!("unsupported encoding: {other}"),
    }
}
