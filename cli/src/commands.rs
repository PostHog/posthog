use std::path::PathBuf;

use anyhow::Context;
use clap::{Parser, Subcommand};
use tracing::{error, warn};

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

    /// Load PostHog credentials from this dotenv-style file when not present in the process
    /// environment. Prefer this over the `--env-file` alias: the npm package runs the binary
    /// through a `node` wrapper, and Node's own built-in `--env-file` flag intercepts that spelling.
    #[arg(long = "dotenv-file", alias = "env-file", value_name = "PATH")]
    env_file: Option<PathBuf>,

    /// Skip artifact processing and upload (sourcemap, dSYM, hermes, proguard) without contacting
    /// PostHog or requiring credentials. Intended for CI gates that bundle to catch regressions but
    /// must not (or cannot) upload. Not for release builds. Pass it before the subcommand
    /// (`posthog-cli --dry-run hermes upload ...`) or set `POSTHOG_CLI_DRY_RUN`. This is distinct
    /// from the `exp endpoints` `--dry-run`, which previews endpoint changes.
    #[arg(
        long,
        env = "POSTHOG_CLI_DRY_RUN",
        value_parser = clap::builder::BoolishValueParser::new(),
        num_args = 0..=1,
        require_equals = true,
        default_value = "false",
        default_missing_value = "true",
    )]
    dry_run: bool,

    #[command(subcommand)]
    command: Commands,
}

/// Commands that `--dry-run` turns into a no-op. Returns the artifact kind, for logging, or `None`
/// for commands that don't upload anything (login, queries, schema sync, symbol-set downloads).
fn dry_run_skipped_command(command: &Commands) -> Option<&'static str> {
    match command {
        Commands::Sourcemap { .. } => Some("sourcemap"),
        Commands::Dsym { .. } => Some("dSYM"),
        Commands::Hermes { .. } => Some("hermes sourcemap"),
        Commands::Proguard { .. } => Some("proguard"),
        Commands::Exp { cmd } => match cmd {
            ExpCommand::Hermes { .. } => Some("hermes sourcemap"),
            ExpCommand::Proguard { .. } => Some("proguard"),
            ExpCommand::Dsym { .. } => Some("dSYM"),
            _ => None,
        },
        _ => None,
    }
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
        if self.dry_run {
            if let Some(kind) = dry_run_skipped_command(&self.command) {
                warn!(
                    "Dry run enabled (--dry-run / POSTHOG_CLI_DRY_RUN): skipping {kind} upload. \
                     Nothing was sent to PostHog and no credentials were used. \
                     Do not use --dry-run for release builds."
                );
                return Ok(());
            }
        }

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
                self.env_file.clone(),
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

#[cfg(test)]
mod tests {
    use super::*;
    use clap::{CommandFactory, Parser};

    #[test]
    fn cli_definition_is_valid() {
        Cli::command().debug_assert();
    }

    #[test]
    fn dry_run_flag_is_wired_to_env_var() {
        let cmd = Cli::command();
        let arg = cmd
            .get_arguments()
            .find(|a| a.get_id().as_str() == "dry_run")
            .expect("dry_run arg should exist");
        assert_eq!(
            arg.get_env(),
            Some(std::ffi::OsStr::new("POSTHOG_CLI_DRY_RUN"))
        );
    }

    #[test]
    fn dry_run_defaults_to_false() {
        let cli = Cli::try_parse_from(["posthog-cli", "login"]).unwrap();
        assert!(!cli.dry_run);
    }

    #[test]
    fn dry_run_flag_sets_true_before_subcommand() {
        let cli = Cli::try_parse_from(["posthog-cli", "--dry-run", "login"]).unwrap();
        assert!(cli.dry_run);
    }

    #[test]
    fn dry_run_classifies_every_command() {
        // (argv, expected kind). `dry_run_skipped_command` matches on the top-level command, so one
        // representative subcommand per family is enough; the `exp` aliases get their own rows.
        let cases: &[(&[&str], Option<&str>)] = &[
            (&["sourcemap", "upload"], Some("sourcemap")),
            (&["dsym", "upload", "--directory", "d"], Some("dSYM")),
            (
                &[
                    "hermes",
                    "clone",
                    "--minified-map-path",
                    "m",
                    "--composed-map-path",
                    "c",
                ],
                Some("hermes sourcemap"),
            ),
            (
                &["proguard", "upload", "--path", "p", "--map-id", "m"],
                Some("proguard"),
            ),
            // hidden `exp` aliases must skip too
            (&["exp", "dsym", "upload", "--directory", "d"], Some("dSYM")),
            (
                &[
                    "exp",
                    "hermes",
                    "clone",
                    "--minified-map-path",
                    "m",
                    "--composed-map-path",
                    "c",
                ],
                Some("hermes sourcemap"),
            ),
            (
                &["exp", "proguard", "upload", "--path", "p", "--map-id", "m"],
                Some("proguard"),
            ),
            // commands that don't upload artifacts must run normally
            (&["login"], None),
            (&["exp", "schema", "status"], None),
            (&["exp", "endpoints", "push", "f.yaml"], None),
        ];

        for (argv, expected) in cases {
            let cli = Cli::try_parse_from(std::iter::once(&"posthog-cli").chain(argv.iter()))
                .unwrap_or_else(|e| panic!("failed to parse {argv:?}: {e}"));
            assert_eq!(
                dry_run_skipped_command(&cli.command),
                *expected,
                "wrong dry-run classification for {argv:?}"
            );
        }
    }

    #[test]
    fn endpoints_dry_run_is_independent_of_top_level_flag() {
        // The `exp endpoints` commands have their own `--dry-run` (preview). The top-level flag is
        // not global, so `exp endpoints push --dry-run` sets only the endpoint flag, and the
        // top-level skip never fires for endpoints — preview semantics stay intact.
        use crate::experimental::endpoints::EndpointCommand;
        let cli = Cli::try_parse_from([
            "posthog-cli",
            "exp",
            "endpoints",
            "push",
            "f.yaml",
            "--dry-run",
        ])
        .unwrap();

        assert!(
            !cli.dry_run,
            "endpoint --dry-run must not set the top-level flag"
        );
        assert_eq!(dry_run_skipped_command(&cli.command), None);

        let Commands::Exp {
            cmd:
                ExpCommand::Endpoints {
                    cmd: EndpointCommand::Push(args),
                },
        } = &cli.command
        else {
            panic!("expected `exp endpoints push`");
        };
        assert!(args.dry_run, "endpoint preview flag should be set");
    }
}
