use clap::{Parser, Subcommand};

use crate::{
    error::CapturedError,
    experimental::{query::command::QueryCommand, tasks::TaskCommand},
    sourcemaps::SourcemapCommand,
    utils::client::SKIP_SSL,
};

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

    #[command(about = "Upload a directory of bundled chunks to PostHog")]
    Sourcemap {
        #[command(subcommand)]
        cmd: SourcemapCommand,
    },
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

    /// Run a SQL query against any data you have in posthog. This is mostly for fun, and subject to change
    Query {
        #[command(subcommand)]
        cmd: QueryCommand,
    },
}

impl Cli {
    pub fn run() -> Result<(), CapturedError> {
        let command = Cli::parse();

        match &command.command {
            Commands::Login => {
                crate::login::login()?;
            }
            Commands::Sourcemap { cmd } => match cmd {
                SourcemapCommand::Inject(input_args) => {
                    crate::sourcemaps::inject::inject(&input_args.directory, &input_args.ignore)?;
                }
                SourcemapCommand::Upload(upload_args) => {
                    crate::sourcemaps::upload::upload(command.host, upload_args.clone())?;
                }
                SourcemapCommand::Process(args) => {
                    crate::sourcemaps::inject::inject(&args.directory, &args.ignore)?;
                    crate::sourcemaps::upload::upload(command.host, args.clone())?;
                }
            },
            Commands::Exp { cmd } => match cmd {
                ExpCommand::Task {
                    cmd,
                    skip_ssl_verification,
                } => {
                    *SKIP_SSL.lock().unwrap() = *skip_ssl_verification;
                    cmd.run()?;
                }
                ExpCommand::Query { cmd } => {
                    crate::experimental::query::command::query_command(command.host, cmd)?
                }
            },
        }

        Ok(())
    }
}
