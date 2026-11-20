pub use crate::utils::xcode::PlistInfo;
use clap::Subcommand;

pub use posthog_symbol_processing::dsym::{find_dsym_bundles, source_bundle, DsymFile};

pub mod upload;

#[derive(Subcommand)]
pub enum DsymSubcommand {
    /// Upload iOS/macOS dSYM files
    Upload(upload::Args),
}
