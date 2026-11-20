pub mod args;
pub mod hermes;
pub mod inject;
pub mod plain;

// The processing itself lives in posthog-symbol-processing, which hog-worker shares.
pub use posthog_symbol_processing::sourcemaps::{constant, content, source_pairs};
