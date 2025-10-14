use clap::Subcommand;
use core::str;

pub mod constant;
pub mod inject;
pub mod source_pair;
pub mod upload;

use crate::sourcemaps::inject::InjectArgs;
use crate::sourcemaps::upload::UploadArgs;

#[derive(Subcommand)]
pub enum SourcemapCommand {
    /// Inject each bundled chunk with a posthog chunk ID
    Inject(InjectArgs),
    /// Upload the bundled chunks to PostHog
    Upload(UploadArgs),
    /// Run inject and upload in one command
    Process(UploadArgs),
}
