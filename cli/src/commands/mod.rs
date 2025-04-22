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
    #[arg(long, default_value = "https://us.posthog.com")]
    host: String,

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

#[derive(Subcommand)]
pub enum SourcemapCommand {
    /// Inject each bundled chunk with a posthog chunk ID
    Inject {
        /// The directory containing the bundled chunks
        #[arg(short, long)]
        directory: PathBuf,
    },
    /// Upload the bundled chunks to PostHog
    Upload {
        /// The directory containing the bundled chunks
        #[arg(short, long)]
        directory: PathBuf,

        /// The build ID to associate with the uploaded chunks
        #[arg(short, long)]
        build: Option<String>,
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
                SourcemapCommand::Inject { directory } => {
                    sourcemap::inject::inject(directory)?;
                }
                SourcemapCommand::Upload { directory, build } => {
                    sourcemap::upload::upload(&command.host, directory, build)?;
                }
            },
            Commands::Query { cmd } => query::query_command(&command.host, cmd)?,
        }

        Ok(())
    }
}
