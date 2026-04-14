use std::path::{Path, PathBuf};

// Debug token, used to get metrics for debug builds - team 89529
const DEBUG_POSTHOG_API_TOKEN: &str = "phc_raG2H9V246hkNZk6K89DZGG98qQyPrKKlicifGlpOXA";

fn generate_api_registry(out_dir: &Path, spec_path: &Path) {
    use openapi_to_rust::{CodeGenerator, GeneratorConfig, SchemaAnalyzer};

    eprintln!("cargo:warning=Generating API registry from {}", spec_path.display());

    let spec_content = std::fs::read_to_string(spec_path)
        .unwrap_or_else(|e| panic!("Failed to read OpenAPI spec at {}: {}", spec_path.display(), e));

    // openapi-to-rust expects 3.1 but PostHog generates 3.0.3.
    // The structural differences that matter (nullable, etc.) don't affect the registry,
    // so patch the version string before parsing.
    let spec_content = spec_content.replacen("\"3.0.3\"", "\"3.1.0\"", 1);

    let spec: serde_json::Value = serde_json::from_str(&spec_content)
        .unwrap_or_else(|e| panic!("Failed to parse OpenAPI spec: {}", e));

    let mut analyzer = SchemaAnalyzer::new(spec)
        .unwrap_or_else(|e| panic!("Failed to analyze OpenAPI spec: {:?}", e));
    let analysis = analyzer.analyze()
        .unwrap_or_else(|e| panic!("Failed to analyze schemas: {:?}", e));

    let config = GeneratorConfig {
        spec_path: spec_path.to_path_buf(),
        output_dir: out_dir.to_path_buf(),
        module_name: "posthog_api".to_string(),
        enable_registry: true,
        registry_only: true,
        enable_async_client: false,
        enable_sse_client: false,
        ..Default::default()
    };

    let generator = CodeGenerator::new(config);
    let registry_code = generator.generate_registry(&analysis)
        .unwrap_or_else(|e| panic!("Failed to generate registry: {:?}", e));

    // The generated code uses //! inner doc comments which don't work inside include!().
    let registry_code = registry_code.replace("//!", "//");

    // The generated code derives serde::Deserialize on structs with &'static [ParamDef]
    // which doesn't implement Deserialize. Strip the Deserialize derive since we only need
    // Serialize for the registry (it's all static data).
    let registry_code = registry_code.replace(
        "serde::Serialize, serde::Deserialize",
        "serde::Serialize",
    );

    let registry_path = out_dir.join("registry.rs");
    std::fs::write(&registry_path, &registry_code)
        .unwrap_or_else(|e| panic!("Failed to write registry to {}: {}", registry_path.display(), e));

    eprintln!(
        "cargo:warning=Generated API registry with {} operations",
        analysis.operations.len()
    );
}

fn generate_empty_registry(out_dir: &Path) {
    let stub = r#"
//! Empty API registry stub — no OpenAPI spec was found at build time.
//! Run `hogli build:openapi-schema` to generate the spec, then rebuild.

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum HttpMethod { Get, Post, Put, Patch, Delete }

impl HttpMethod {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Get => "GET", Self::Post => "POST", Self::Put => "PUT",
            Self::Patch => "PATCH", Self::Delete => "DELETE",
        }
    }
}

impl std::fmt::Display for HttpMethod {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum ParamLocation { Path, Query, Header }

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum ParamType { String, Integer, Number, Boolean }

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum BodyContentType { Json, FormUrlEncoded, Multipart, OctetStream, TextPlain }

#[derive(Debug, Clone, serde::Serialize)]
pub struct ParamDef {
    pub name: &'static str,
    pub location: ParamLocation,
    pub required: bool,
    pub param_type: ParamType,
    pub description: Option<&'static str>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct BodyDef {
    pub content_type: BodyContentType,
    pub schema_name: Option<&'static str>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct OperationDef {
    pub id: &'static str,
    pub method: HttpMethod,
    pub path: &'static str,
    pub summary: Option<&'static str>,
    pub description: Option<&'static str>,
    pub params: &'static [ParamDef],
    pub body: Option<BodyDef>,
    pub response_schema: Option<&'static str>,
}

pub fn find_operation(id: &str) -> Option<&'static OperationDef> {
    OPERATIONS.iter().find(|op| op.id == id)
}

pub fn operation_ids() -> impl Iterator<Item = &'static str> {
    OPERATIONS.iter().map(|op| op.id)
}

pub static OPERATIONS: [OperationDef; 0] = [];
"#;
    let registry_path = out_dir.join("registry.rs");
    std::fs::write(&registry_path, stub)
        .unwrap_or_else(|e| panic!("Failed to write stub registry: {}", e));

    eprintln!("cargo:warning=No OpenAPI spec found. Run `hogli build:openapi-schema` then rebuild.");
}

pub fn main() {
    let profile = std::env::var("PROFILE").expect("Profile variable is set by cargo");
    if profile == "debug" {
        println!("cargo:rustc-env=POSTHOG_API_TOKEN={DEBUG_POSTHOG_API_TOKEN}");
    } else {
        eprintln!("Not setting debug posthog api token");
    }

    let out_dir = PathBuf::from(std::env::var("OUT_DIR").expect("OUT_DIR is set by cargo"));

    // Look for the OpenAPI spec in the standard location (generated by `hogli build:openapi-schema`)
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set"));
    let spec_path = manifest_dir.join("../frontend/tmp/openapi.json");

    if spec_path.exists() {
        println!("cargo:rerun-if-changed={}", spec_path.display());
        generate_api_registry(&out_dir, &spec_path);
    } else {
        generate_empty_registry(&out_dir);
    }
}
