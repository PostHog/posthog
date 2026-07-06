use std::path::PathBuf;

use anyhow::Context;
use clap::{Parser, Subcommand};
use tracing::{debug, error, warn};

use crate::{
    api_proxy,
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

    /// Skip SSL certificate verification when talking to the PostHog API. Use only with
    /// self-signed certificates.
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
        Commands::SymbolSets {
            cmd: SymbolSetsSubcommand::Upload(_),
        } => Some("native debug symbols"),
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

// These are the API key env vars recognized by the Node `posthog-cli api` bundle.
// Rust auth only reads the POSTHOG_CLI_* aliases; this check is deliberately about
// whether the child process already has a usable key, so we avoid loading and mixing
// stored credentials.
const API_KEY_ENV_VARS: &[&str] = &[
    "POSTHOG_API_KEY",
    "POSTHOG_CLI_API_KEY",
    "POSTHOG_CLI_TOKEN",
];

fn api_command_needs_stored_credentials_with_env(
    args: &[String],
    has_env: impl Fn(&str) -> bool,
) -> bool {
    let Some(command) = args.first().map(String::as_str) else {
        return false;
    };

    command == "call"
        && !args.iter().skip(1).any(|arg| arg == "--dry-run")
        && !API_KEY_ENV_VARS.iter().any(|name| has_env(name))
}

fn api_command_needs_stored_credentials(args: &[String]) -> bool {
    api_command_needs_stored_credentials_with_env(args, |name| std::env::var_os(name).is_some())
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

    #[command(about = "Upload, download, and manage symbol sets")]
    SymbolSets {
        #[command(subcommand)]
        cmd: SymbolSetsSubcommand,
    },

    #[command(
        about = "Agent-first PostHog API tools",
        long_about = "Agent-first PostHog API tools.\n\n\
            Exposes PostHog's MCP tool catalog through a shell-friendly interface so coding \
            agents (and the humans driving them) can discover, inspect, and call PostHog API \
            tools without loading every schema into context upfront.",
        after_help = "Commands:\n  \
            tools                                              List every available tool\n  \
            search <regex>                                     Find tools by name, title, or description\n  \
            info [--json] <tool>                               Show a tool's description and input schema\n  \
            schema <tool> [field.path]                         Drill into a nested schema field\n  \
            call [--json] [--dry-run] [--confirm] <tool> '<json>'  Execute a tool with JSON input\n  \
            skill list [--json]                                List installable PostHog agent skills\n  \
            skill install [--force] <skill-id>                 Install a skill into .agents/skills/\n  \
            agents-md install [--path AGENTS.md]               Install the PostHog steering snippet\n\n\
            Run `posthog-cli api --agent-help` for the full agent-facing usage guide.\n\n\
            Destructive tools require --confirm. Use --dry-run before mutations.\n\n\
            Limitation: `login` grants the MCP scope set minus the writes PostHog \
            withholds from long-lived API keys, so a few tools (desktop file-system \
            writes, integration deletes, reminder and user-settings writes) are not \
            available through this command.",
        trailing_var_arg = true
    )]
    Api {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
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
                | Commands::Api { .. }
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
                SymbolSetsSubcommand::Upload(args) => {
                    crate::debug_symbols::upload::upload(&args)?;
                }
                SymbolSetsSubcommand::Download(args) => {
                    crate::download::download(&args)?;
                }
                SymbolSetsSubcommand::Extract(args) => {
                    crate::download::extract(&args)?;
                }
            },
            Commands::Api { args } => {
                let api_context = if api_command_needs_stored_credentials(&args) {
                    match init_context(
                        self.host.clone(),
                        self.skip_ssl_verification,
                        self.rate_limit,
                        self.env_file.clone(),
                    ) {
                        Ok(_) => Some(context()),
                        Err(error) => {
                            debug!("API CLI proxy running without invocation context: {error:?}");
                            None
                        }
                    }
                } else {
                    None
                };
                api_proxy::run(args, self.host, api_context)?;
            }
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
    fn api_metadata_commands_do_not_need_stored_credentials() {
        let cases: &[&[&str]] = &[
            &[],
            &["--agent-help"],
            &["tools"],
            &["search", "feature-flag"],
            &["info", "feature-flag-get-all"],
            &["schema", "query-trends", "series"],
            &["skill", "list"],
            &["agents-md", "install"],
        ];

        for argv in cases {
            let args = argv.iter().map(|arg| arg.to_string()).collect::<Vec<_>>();
            assert!(
                !api_command_needs_stored_credentials_with_env(&args, |_| false),
                "metadata command should not load stored credentials: {argv:?}"
            );
        }
    }

    #[test]
    fn api_call_uses_stored_credentials_only_when_needed() {
        let call_args = ["call", "--json", "feature-flag-get-all", "{\"limit\":5}"]
            .iter()
            .map(|arg| arg.to_string())
            .collect::<Vec<_>>();

        assert!(api_command_needs_stored_credentials_with_env(
            &call_args,
            |_| false
        ));
        assert!(!api_command_needs_stored_credentials_with_env(
            &call_args,
            |name| name == "POSTHOG_API_KEY"
        ));

        let dry_run_args = [
            "call",
            "--dry-run",
            "feature-flags-bulk-delete-create",
            "{\"ids\":[123]}",
        ]
        .iter()
        .map(|arg| arg.to_string())
        .collect::<Vec<_>>();

        assert!(!api_command_needs_stored_credentials_with_env(
            &dry_run_args,
            |_| false
        ));
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
