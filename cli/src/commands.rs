use anyhow::Context;
use clap::{Parser, Subcommand};
use tracing::error;

use crate::{
    download::SymbolSetsSubcommand,
    dsym::DsymSubcommand,
    error::CapturedError,
    experimental::{endpoints::EndpointCommand, query::command::QueryCommand, tasks::TaskCommand},
    invocation_context::{context, init_context, INVOCATION_CONTEXT},
    proguard::ProguardSubcommand,
    sourcemaps::{hermes::HermesSubcommand, plain::SourcemapCommand},
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

    #[arg(long, default_value = "false")]
    skip_ssl_verification: bool,

    /// Set the number of requests per minute for the Posthog API Client.
    #[arg(long, env = "POSTHOG_CLIENT_RATE_LIMIT")]
    rate_limit: Option<usize>,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Interactively authenticate with PostHog, storing a personal API token locally. You can also use the
    /// environment variables `POSTHOG_CLI_API_KEY` and `POSTHOG_CLI_PROJECT_ID`
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

    #[command(about = "Upload Apple dSYM debug symbol files to PostHog")]
    Dsym {
        #[command(subcommand)]
        cmd: DsymSubcommand,
    },

    #[command(about = "Upload hermes sourcemaps to PostHog")]
    Hermes {
        #[command(subcommand)]
        cmd: HermesSubcommand,
    },

    #[command(about = "Upload proguard mapping files to PostHog")]
    Proguard {
        #[command(subcommand)]
        cmd: ProguardSubcommand,
    },

    #[command(about = "Manage uploaded symbol sets")]
    SymbolSets {
        #[command(subcommand)]
        cmd: SymbolSetsSubcommand,
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

    /// Manage PostHog endpoints as YAML files. Pull endpoints from PostHog, or push changes from your YAML files.
    Endpoints {
        #[command(subcommand)]
        cmd: EndpointCommand,
    },

    // TODO(sept 2026): remove these backward-compat aliases, they moved to top-level commands
    #[command(about = "Upload hermes sourcemaps to PostHog", hide = true)]
    Hermes {
        #[command(subcommand)]
        cmd: HermesSubcommand,
    },

    #[command(about = "Upload proguard mapping files to PostHog", hide = true)]
    Proguard {
        #[command(subcommand)]
        cmd: ProguardSubcommand,
    },

    #[command(about = "Upload iOS/macOS dSYM files to PostHog", hide = true)]
    Dsym {
        #[command(subcommand)]
        cmd: DsymSubcommand,
    },

    /// Download event definitions and generate typed SDK
    Schema {
        #[command(subcommand)]
        cmd: SchemaCommand,
    },
}

#[derive(Subcommand)]
pub enum SchemaCommand {
    /// Download event definitions and generate typed SDK
    Pull {
        /// Output path for generated definitions (stored in posthog.json for future runs)
        #[arg(short, long)]
        output: Option<String>,
    },
    /// Show current schema sync status
    Status,
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
        if !matches!(
            self.command,
            Commands::Login
                | Commands::SymbolSets {
                    cmd: SymbolSetsSubcommand::Extract(_)
                }
        ) {
            init_context(
                self.host.clone(),
                self.skip_ssl_verification,
                self.rate_limit,
            )?;
        }

        match self.command {
            Commands::Login => {
                // Notably login doesn't have a context set up going it - it sets one up
                crate::login::login(self.host)?;
            }
            Commands::Sourcemap { cmd } => match cmd {
                SourcemapCommand::Inject(input_args) => {
                    crate::sourcemaps::plain::inject::inject(&input_args, None)?;
                }
                SourcemapCommand::Upload(upload_args) => {
                    crate::sourcemaps::plain::upload::upload(&upload_args, None)?;
                }
                SourcemapCommand::Process(args) => {
                    let (inject_args, upload_args) = args.resolve_stdin()?.into();
                    let cwd =
                        std::env::current_dir().context("Failed to determine current directory")?;
                    let release = crate::sourcemaps::inject::get_release_for_maps(
                        &cwd,
                        inject_args.release.clone(),
                        std::iter::empty(),
                    )?;
                    crate::sourcemaps::plain::inject::inject(&inject_args, release.as_ref())?;
                    crate::sourcemaps::plain::upload::upload(&upload_args, release.as_ref())?;
                }
            },
            Commands::Dsym { cmd } => match cmd {
                DsymSubcommand::Upload(args) => {
                    crate::dsym::upload::upload(&args)?;
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
            Commands::Proguard { cmd } => match cmd {
                ProguardSubcommand::Upload(args) => {
                    crate::proguard::upload::upload(&args)?;
                }
            },
            Commands::SymbolSets { cmd } => match cmd {
                SymbolSetsSubcommand::Download(args) => {
                    crate::download::download(&args)?;
                }
                SymbolSetsSubcommand::Extract(args) => {
                    crate::download::extract(&args)?;
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
                ExpCommand::Endpoints { cmd } => {
                    cmd.run()?;
                }
                // TODO(sept 2026): remove these backward-compat aliases
                ExpCommand::Hermes { cmd } => match cmd {
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
                ExpCommand::Proguard { cmd } => match cmd {
                    ProguardSubcommand::Upload(args) => {
                        crate::proguard::upload::upload(&args)?;
                    }
                },
                ExpCommand::Dsym { cmd } => match cmd {
                    DsymSubcommand::Upload(args) => {
                        crate::dsym::upload::upload(&args)?;
                    }
                },
                ExpCommand::Schema { cmd } => match cmd {
                    SchemaCommand::Pull { output } => {
                        crate::experimental::schema::pull(self.host, output)?;
                    }
                    SchemaCommand::Status => {
                        crate::experimental::schema::status()?;
                    }
                },
            },
        }

        if INVOCATION_CONTEXT.get().is_some() {
            context().finish();
        }

        Ok(())
    }
}
