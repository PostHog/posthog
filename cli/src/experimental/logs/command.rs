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

use anyhow::Result;

use super::config::LokiImportConfig;
use super::loki::{LokiAuth, LokiClient};
use super::mapping::Mapper;
use super::plan::{render, RunPlan};

/// How many records a dry run pulls to prove the mapping. Large enough that a rule matching a
/// minority of records still shows a non-zero count, small enough to return in seconds.
const SAMPLE_RECORDS: usize = 100;

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
            ImportSource::Loki {
                config,
                checkpoint,
                dry_run,
            } => {
                let text = std::fs::read_to_string(config).map_err(|error| {
                    anyhow::anyhow!("cannot read {}: {error}", config.display())
                })?;
                let parsed = LokiImportConfig::parse(&text)?;

                if *dry_run {
                    return dry_run_report(&parsed);
                }

                run_import(&parsed, checkpoint)
            }
        }
    }
}

fn dry_run_report(config: &LokiImportConfig) -> Result<()> {
    let client = LokiClient::new(
        &config.source,
        LokiAuth::from_env(),
        reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(120))
            .build()?,
    );
    let mapper = Mapper::new(config.extract.clone())?;

    let mut volume = 0;
    let mut sample = Vec::new();
    for selector in &config.range.select {
        volume += client.volume_bytes(selector, config.range.from, config.range.to)?;
        if sample.len() < SAMPLE_RECORDS {
            let (entries, _) = client.query_page(
                selector,
                config.range.from.timestamp_nanos_opt().unwrap_or_default(),
                config.range.to,
            )?;
            sample.extend(entries.into_iter().take(SAMPLE_RECORDS - sample.len()));
        }
    }

    let hits = mapper.hits(&sample);
    let mapped: Vec<_> = sample.iter().map(|entry| mapper.map(entry)).collect();
    // First record that actually carried each field. Reading only the first record would report
    // NOT FOUND for a field most records have, in the output built to prevent exactly that.
    let samples = [
        (
            "service_name",
            mapped.iter().find_map(|r| r.service_name.clone()),
        ),
        (
            "severity",
            mapped
                .iter()
                .find_map(|r| r.severity.as_ref().map(|(text, _)| text.clone())),
        ),
        ("trace_id", mapped.iter().find_map(|r| r.trace_id.clone())),
        ("span_id", mapped.iter().find_map(|r| r.span_id.clone())),
    ];

    let sample_bytes: u64 = sample.iter().map(|entry| entry.line.len() as u64).sum();
    let plan = RunPlan::build(config, volume, sample.len() as u64, sample_bytes);
    print!("{}", render(config, &plan, &hits, &samples));
    Ok(())
}

fn run_import(config: &LokiImportConfig, checkpoint: &std::path::Path) -> Result<()> {
    use super::run::{intake_url, project_key_from_env, Importer};

    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()?;
    let client = LokiClient::new(&config.source, LokiAuth::from_env(), http.clone());
    let mapper = Mapper::new(config.extract.clone())?;
    // The CLI already resolved the host from --host, then the stored login, then the default.
    // Re-deriving it here would send an EU project's logs to US.
    let host = crate::invocation_context::context().config.host.clone();

    Importer {
        config,
        loki: &client,
        mapper: &mapper,
        http: &http,
        intake_url: intake_url(&host, config.range.from),
        project_key: project_key_from_env()?,
        checkpoint_path: checkpoint,
    }
    .run()
}
