use clap::Subcommand;

pub use posthog_symbol_processing::proguard::ProguardFile;

pub mod upload;

#[derive(Subcommand)]
pub enum ProguardSubcommand {
    /// Upload proguard mapping files
    Upload(upload::Args),
}
