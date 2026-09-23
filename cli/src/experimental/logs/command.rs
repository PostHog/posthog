use std::path::PathBuf;

use clap::Subcommand;

#[derive(Debug, Subcommand)]
pub enum LogsCommand {
    /// Import historical logs from another log store into PostHog
    Import {
        #[command(subcommand)]
        cmd: ImportSource,
    },
}

#[derive(Debug, Subcommand)]
pub enum ImportSource {
    /// Read from Grafana Loki. Credentials come from LOKI_BEARER_TOKEN, or LOKI_USERNAME and
    /// LOKI_PASSWORD for Grafana Cloud.
    Loki {
        /// Path to the import config. Its shape is documented in cli/src/experimental/logs/README.md.
        #[arg(long)]
        config: PathBuf,

        /// Where to record progress. A resumed run re-sends only the shard it was inside.
        #[arg(long, default_value = "loki-import.state")]
        checkpoint: PathBuf,

        /// Report the size, duration and mapping coverage of the run without sending anything.
        #[arg(long, default_value_t = false)]
        dry_run: bool,
    },
}

use anyhow::{bail, Result};

impl LogsCommand {
    pub fn run(&self) -> Result<()> {
        match self {
            LogsCommand::Import { cmd } => cmd.run(),
        }
    }
}

impl ImportSource {
    fn run(&self) -> Result<()> {
        match self {
            ImportSource::Loki { config, .. } => {
                // Parsing and validating the config is the whole of this layer. Reading Loki and
                // sending to the intake arrives with the engine.
                let text = std::fs::read_to_string(config).map_err(|error| {
                    anyhow::anyhow!("cannot read {}: {error}", config.display())
                })?;
                super::config::LokiImportConfig::parse(&text)?;

                bail!(
                    "this build validates the import config but cannot run an import yet. \
                     The config at {} parsed cleanly.",
                    config.display()
                )
            }
        }
    }
}
