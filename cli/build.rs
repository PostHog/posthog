use std::env;
use std::fs;
use std::path::PathBuf;

// Debug token, used to get metrics for debug builds - team 89529
const DEBUG_POSTHOG_API_TOKEN: &str = "phc_raG2H9V246hkNZk6K89DZGG98qQyPrKKlicifGlpOXA";
const API_CLI_BUNDLE: &str = "lib/posthog-api-cli.mjs";

fn write_api_cli_bundle_include() {
    let manifest_dir =
        PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set by cargo"));
    let bundle_path = manifest_dir.join(API_CLI_BUNDLE);
    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR is set by cargo"));
    let out_path = out_dir.join("api_cli_bundle.rs");

    println!("cargo:rerun-if-changed={}", bundle_path.display());

    let contents = if bundle_path.is_file() {
        let bundle_path_literal = format!("{bundle_path:?}");
        format!("const EMBEDDED_API_CLI_BUNDLE: Option<&[u8]> = Some(include_bytes!({bundle_path_literal}));\n")
    } else {
        "const EMBEDDED_API_CLI_BUNDLE: Option<&[u8]> = None;\n".to_string()
    };

    fs::write(out_path, contents).expect("write embedded API CLI bundle include");
}

// This build file just sets this token for debug builds - for production builds, we use the token from our CI's secrets
pub fn main() {
    write_api_cli_bundle_include();

    let profile = env::var("PROFILE").expect("Profile variable is set by cargo");
    if profile == "debug" {
        println!("cargo:rustc-env=POSTHOG_API_TOKEN={DEBUG_POSTHOG_API_TOKEN}");
    } else {
        eprintln!("Not setting debug posthog api token");
    }
}
