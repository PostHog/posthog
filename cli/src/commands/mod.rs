pub mod login;
pub mod query;
pub mod sourcemap;
pub mod tasks;

use clap::{Parser, Subcommand};
use query::QueryCommand;
use std::path::PathBuf;

use crate::{commands::tasks::TaskCommand, error::CapturedError, utils::client::SKIP_SSL};

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

    /// Experimental commands, not quite ready for prime time
    Exp {
        #[command(subcommand)]
        cmd: ExpCommand,
    },

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

#[derive(clap::Args, Clone)]
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

    /// The maximum number of chunks to upload in a single batch
    #[arg(long, default_value = "50")]
    batch_size: usize,
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

#[derive(Subcommand)]
pub enum ExpCommand {
    /// Manage tasks - list, create, update, delete etc
    Task {
        #[command(subcommand)]
        cmd: TaskCommand,
        /// Whether to skip SSL verification when talking to the posthog API - only use when using self-signed certificates for
        /// self-deployed instances
        // TODO - it seems likely we won't support tasks for self hosted, but I'm putting this here in case we do
        #[arg(long, default_value = "false")]
        skip_ssl_verification: bool,
    },
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
                    sourcemap::upload::upload(command.host, upload_args.clone())?;
                }
                SourcemapCommand::Process(args) => {
                    sourcemap::inject::inject(&args.directory, &args.ignore)?;
                    sourcemap::upload::upload(command.host, args.clone())?;
                }
            },
            Commands::Query { cmd } => query::query_command(command.host, cmd)?,
            Commands::Exp { cmd } => match cmd {
                ExpCommand::Task {
                    cmd,
                    skip_ssl_verification,
                } => {
                    *SKIP_SSL.lock().unwrap() = *skip_ssl_verification;
                    cmd.run()?;
                }
            },
        }

        Ok(())
    }
}
