use clap::Subcommand;

pub mod sources;
pub mod upload;

#[derive(Subcommand)]
pub enum JvmSubcommand {
    /// Upload the Java and Kotlin source files of a build, so PostHog shows the code around each
    /// stack frame of its exceptions
    Upload(upload::Args),
}
