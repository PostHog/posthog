use clap::{Parser, Subcommand};

use crate::{
    error::CapturedError,
    experimental::{query::command::QueryCommand, tasks::TaskCommand},
    invocation_context::{context, init_context},
    sourcemaps::{hermes::HermesSubcommand, web::SourcemapCommand},
};

#[derive(Parser)]
#[command(version, about, long_about = None)]
pub struct Cli {
    /// The PostHog host to connect to
    #[arg(long)]
    host: Option<String>,

    #[arg(long, default_value = "false")]
    skip_ssl_verification: bool,

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

    #[command(about = "Upload hermes sourcemaps to PostHog")]
    Hermes {
        #[command(subcommand)]
        cmd: HermesSubcommand,
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

        if !matches!(command.command, Commands::Login) {
            init_context(command.host.clone(), command.skip_ssl_verification)?;
        }

        match command.command {
            Commands::Login => {
                // Notably login doesn't have a context set up going it - it sets one up
                crate::login::login()?;
            }
            Commands::Sourcemap { cmd } => match cmd {
                SourcemapCommand::Inject(input_args) => {
                    crate::sourcemaps::web::inject::inject(&input_args)?;
                }
                SourcemapCommand::Upload(upload_args) => {
                    crate::sourcemaps::web::upload::upload(&upload_args)?;
                }
                SourcemapCommand::Process(args) => {
                    let (inject, upload) = args.into();
                    crate::sourcemaps::web::inject::inject(&inject)?;
                    crate::sourcemaps::web::upload::upload(&upload)?;
                }
            },
            Commands::Exp { cmd } => match cmd {
                ExpCommand::Task {
                    cmd,
                    skip_ssl_verification: _,
                } => {
                    cmd.run()?;
                }
                ExpCommand::Query { cmd } => {
                    crate::experimental::query::command::query_command(&cmd)?
                }
            },
            Commands::Hermes { cmd } => match cmd {
                HermesSubcommand::Inject(args) => {
                    crate::sourcemaps::hermes::inject::inject(&args)?;
                }
                HermesSubcommand::Upload(args) => {
                    crate::sourcemaps::hermes::upload::upload(&args)?;
                }
                HermesSubcommand::Clone(args) => {
                    crate::sourcemaps::hermes::clone::clone(&args)?;
                }
            },
        }

        context().finish();

        Ok(())
    }
}
