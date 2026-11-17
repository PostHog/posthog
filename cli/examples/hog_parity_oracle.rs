//! Reference outputs for hog's byte-parity tests.
//!
//! hog (the TypeScript CLI in `hog/`) must upload the same bytes and content hashes as this crate,
//! or PostHog rejects re-uploads with `content_hash_mismatch`. This example runs the crate's own code
//! with the crate's own Cargo.lock, so the goldens it prints come from exactly what posthog-cli ships.
//! `hog/test/parity/README.md` explains how to regenerate the goldens with it.
//!
//! Usage:
//!   cargo run --release --example hog_parity_oracle -- container <type> <file> [<out>]
//!     Prints the SHA-512 content hash of the container for <file>, and writes the container to <out>
//!     when given. <type> is one of: proguard, hermes, dsym, elf.
//!   cargo run --release --example hog_parity_oracle -- release-hash <name> <version>

use posthog_cli::utils::files::content_hash;
use posthog_symbol_data::{write_symbol_data, AppleDsym, ElfDebugInfo, HermesMap, ProguardMapping};

fn main() {
    // nosemgrep: rust.lang.security.args.args -- a local test tool, argv only names fixture files
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("container") => {
            let input = std::fs::read(&args[3]).expect("read input");
            let data = match args[2].as_str() {
                "proguard" => write_symbol_data(ProguardMapping {
                    content: String::from_utf8(input).expect("utf-8 mapping"),
                }),
                "hermes" => write_symbol_data(HermesMap {
                    sourcemap: String::from_utf8(input).expect("utf-8 map"),
                }),
                "dsym" => write_symbol_data(AppleDsym { data: input }),
                "elf" => write_symbol_data(ElfDebugInfo { data: input }),
                other => panic!("unknown container type {other}"),
            }
            .expect("write symbol data");
            println!("{}", content_hash([&data]));
            if let Some(out) = args.get(4) {
                std::fs::write(out, &data).expect("write container");
            }
        }
        Some("release-hash") => println!("{}", content_hash([args[2].as_bytes(), args[3].as_bytes()])),
        _ => panic!("usage: hog_parity_oracle container <type> <file> [<out>] | release-hash <name> <version>"),
    }
}
