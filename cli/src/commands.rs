use clap::{Parser, Subcommand};
use tracing::error;

use crate::{
    error::CapturedError,
    experimental::{query::command::QueryCommand, tasks::TaskCommand},
    invocation_context::{context, init_context},
    sourcemaps::SourcemapCommand,
};

#[derive(Parser)]
#[command(version, about, long_about = None)]
pub struct Cli {
    /// The PostHog host to connect to
    #[arg(long)]
    host: Option<String>,

    /// Disable non-zero exit codes on errors. Use with caution.
    #[arg(long, default_value = "false")]
    no_fail: bool,

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
        let no_fail = command.no_fail;

        match command.run_impl() {
            Ok(_) => Ok(()),
            Err(e) => {
                let msg = match &e.exception_id {
                    Some(id) => format!("Oops! {} (ID: {})", e.inner, id),
                    None => format!("Oops! {:?}", e.inner),
                };
                error!(msg);
                if no_fail {
                    Ok(())
                } else {
                    Err(e)
                }
            }
        }
    }

    fn run_impl(self) -> Result<(), CapturedError> {
        match self.command {
            Commands::Login => {
                // Notably login doesn't have a context set up going it - it sets one up
                crate::login::login()?;
            }
            Commands::Sourcemap { cmd } => match cmd {
                SourcemapCommand::Inject(input_args) => {
                    init_context(self.host.clone(), false)?;
                    crate::sourcemaps::inject::inject(&input_args)?;
                }
                SourcemapCommand::Upload(upload_args) => {
                    init_context(self.host.clone(), upload_args.skip_ssl_verification)?;
                    crate::sourcemaps::upload::upload_cmd(upload_args.clone())?;
                }
                SourcemapCommand::Process(args) => {
                    init_context(self.host.clone(), args.skip_ssl_verification)?;
                    let (inject, upload) = args.into();
                    crate::sourcemaps::inject::inject(&inject)?;
                    crate::sourcemaps::upload::upload_cmd(upload)?;
                }
            },
            Commands::Exp { cmd } => match cmd {
                ExpCommand::Task {
                    cmd,
                    skip_ssl_verification,
                } => {
                    init_context(self.host.clone(), skip_ssl_verification)?;
                    cmd.run()?;
                }
                ExpCommand::Query { cmd } => {
                    init_context(self.host.clone(), false)?;
                    crate::experimental::query::command::query_command(&cmd)?
                }
            },
        }

        context().finish();

        Ok(())
    }
}
