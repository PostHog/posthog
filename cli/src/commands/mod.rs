pub mod login;
pub mod query;
pub mod sourcemap;

use clap::{Parser, Subcommand};
use query::QueryCommand;
use std::path::PathBuf;

use crate::error::CapturedError;

#[derive(Parser)]
#[command(version, about, long_about = None)]
pub struct Cli {
    /// The PostHog host to connect to
    #[arg(long)]
    host: Option<String>,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Interactively authenticate with PostHog, storing a personal API token locally. You can also use the
    /// environment variables `POSTHOG_CLI_TOKEN` and `POSTHOG_CLI_ENV_ID`
    Login,

    /// Run a SQL query against any data you have in posthog. This is mostly for fun, and subject to change
    Query {
        #[command(subcommand)]
        cmd: QueryCommand,
    },

    #[command(about = "Upload a directory of bundled chunks to PostHog")]
    Sourcemap {
        #[command(subcommand)]
        cmd: SourcemapCommand,
    },
}

#[derive(clap::Args)]
pub struct InjectArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    ignore: Vec<String>,
}

#[derive(clap::Args)]
pub struct UploadArgs {
    /// The directory containing the bundled chunks
    #[arg(short, long)]
    directory: PathBuf,

    /// One or more directory glob patterns to ignore
    #[arg(short, long)]
    ignore: Vec<String>,

    /// The project name associated with the uploaded chunks. Required to have the uploaded chunks associated with
    /// a specific release, auto-discovered from git information on disk if not provided.
    #[arg(long)]
    project: Option<String>,

    /// The version of the project - this can be a version number, semantic version, or a git commit hash. Required
    /// to have the uploaded chunks associated with a specific release. Auto-discovered from git information on
    /// disk if not provided.
    #[arg(long)]
    version: Option<String>,

    /// Whether to delete the source map files after uploading them
    #[arg(long, default_value = "false")]
    delete_after: bool,

    /// Whether to skip SSL verification when uploading chunks - only use when using self-signed certificates for
    /// self-deployed instances
    #[arg(long, default_value = "false")]
    skip_ssl_verification: bool,
}

#[derive(Subcommand)]
pub enum SourcemapCommand {
    /// Inject each bundled chunk with a posthog chunk ID
    Inject(InjectArgs),
    /// Upload the bundled chunks to PostHog
    Upload(UploadArgs),
    /// Run inject and upload in one command
    Process(UploadArgs),
}

impl Cli {
    pub fn run() -> Result<(), CapturedError> {
        let command = Cli::parse();

        match &command.command {
            Commands::Login => {
                login::login()?;
            }
            Commands::Sourcemap { cmd } => match cmd {
                SourcemapCommand::Inject(input_args) => {
                    sourcemap::inject::inject(&input_args.directory, &input_args.ignore)?;
                }
                SourcemapCommand::Upload(upload_args) => {
                    let UploadArgs {
                        directory,
                        ignore,
                        project,
                        version,
                        delete_after,
                        skip_ssl_verification,
                    } = upload_args;
                    sourcemap::upload::upload(
                        command.host,
                        directory,
                        ignore,
                        project.clone(),
                        version.clone(),
                        *delete_after,
                        *skip_ssl_verification,
                    )?;
                }
                SourcemapCommand::Process(args) => {
                    let UploadArgs {
                        directory,
                        project,
                        ignore,
                        version,
                        delete_after,
                        skip_ssl_verification,
                    } = args;

                    sourcemap::inject::inject(directory, ignore)?;
                    sourcemap::upload::upload(
                        command.host,
                        directory,
                        ignore,
                        project.clone(),
                        version.clone(),
                        *delete_after,
                        *skip_ssl_verification,
                    )?;
                }
            },
            Commands::Query { cmd } => query::query_command(command.host, cmd)?,
        }

        Ok(())
    }
}
