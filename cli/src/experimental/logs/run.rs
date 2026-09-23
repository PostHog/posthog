use std::collections::HashSet;
use std::path::Path;
use std::thread::sleep;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use reqwest::blocking::Client;

use super::checkpoint::Checkpoint;
use super::config::LokiImportConfig;
use super::emit::{batch_records, Batch};
use super::loki::LokiClient;
use super::mapping::Mapper;
use super::send::{classify, Disposition};
use super::shard::shards;

/// The intake rejects a personal API token, so the import takes the project write key. That key is
/// already public-facing, which keeps a long unattended run off the user's personal credential.
const PROJECT_KEY_VAR: &str = "POSTHOG_PROJECT_API_KEY";

const MAX_ATTEMPTS: u32 = 8;

/// Paces sending so an import cannot saturate the intake, which has no rate limiting of its own.
struct Pacer {
    per_second: u32,
    window_start: Instant,
    sent_in_window: u32,
}

impl Pacer {
    fn new(per_second: u32) -> Self {
        Self {
            per_second,
            window_start: Instant::now(),
            sent_in_window: 0,
        }
    }

    /// Sleeps out the rest of the current second once the allowance is spent, repeating while the
    /// carried debt still exceeds one second's worth.
    fn record(&mut self, records: u32) {
        self.sent_in_window = self.sent_in_window.saturating_add(records);

        while self.sent_in_window >= self.per_second {
            let elapsed = self.window_start.elapsed();
            if elapsed < Duration::from_secs(1) {
                sleep(Duration::from_secs(1) - elapsed);
            }
            self.window_start = Instant::now();
            // Subtract rather than reset, so a batch larger than the allowance is paid for over
            // the seconds that follow instead of being forgiven.
            self.sent_in_window = self.sent_in_window.saturating_sub(self.per_second);
        }
    }
}

/// Cheap identity for a log line at a shared timestamp, so the boundary dedup set stays small.
fn line_key(line: &str) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    line.hash(&mut hasher);
    hasher.finish()
}

pub struct Importer<'a> {
    pub config: &'a LokiImportConfig,
    pub loki: &'a LokiClient,
    pub mapper: &'a Mapper,
    pub http: &'a Client,
    pub intake_url: String,
    pub project_key: String,
    pub checkpoint_path: &'a Path,
}

pub fn project_key_from_env() -> Result<String> {
    let key = std::env::var(PROJECT_KEY_VAR).unwrap_or_default();
    if key.is_empty() {
        bail!(
            "set {PROJECT_KEY_VAR} to the project API key for the project you are importing into. \
             The intake rejects a personal API token."
        );
    }
    Ok(key)
}

impl Importer<'_> {
    pub fn run(&self) -> Result<()> {
        let mut checkpoint = Checkpoint::load(self.checkpoint_path)?;
        let width = self.config.tuning.shard.seconds();
        let mut pacer = Pacer::new(self.config.tuning.max_records_per_second.get());

        let from_ns = self
            .config
            .range
            .from
            .timestamp_nanos_opt()
            .context("range.from is outside the nanosecond range")?;
        let to_ns = self
            .config
            .range
            .to
            .timestamp_nanos_opt()
            .context("range.to is outside the nanosecond range")?;
        if checkpoint.reconcile_range(from_ns, to_ns) {
            eprintln!(
                "the configured range now starts earlier than the checkpoint covers, so previous \
                 progress was discarded and the whole range will be imported"
            );
        }

        for selector in &self.config.range.select {
            let windows = shards(
                self.config.range.from,
                self.config.range.to,
                width,
                checkpoint.resume_from(selector),
            );

            for window in windows {
                let mut cursor = window
                    .start
                    .timestamp_nanos_opt()
                    .context("shard start is outside the nanosecond range")?;
                let mut records_in_shard = 0u64;
                let mut bytes_in_shard = 0u64;
                // Lines already sent at exactly `cursor`. The page resumes at that instant rather
                // than past it, so this is what stops the boundary entries arriving twice.
                let mut sent_at_cursor: HashSet<u64> = HashSet::new();

                loop {
                    let (entries, next) = self.loki.query_page(selector, cursor, window.end)?;
                    if entries.is_empty() {
                        break;
                    }

                    let fresh: Vec<_> = entries
                        .into_iter()
                        .filter(|entry| {
                            entry.timestamp_ns != cursor
                                || !sent_at_cursor.contains(&line_key(&entry.line))
                        })
                        .collect();

                    let mapped: Vec<_> = fresh.iter().map(|e| self.mapper.map(e)).collect();
                    for batch in batch_records(&mapped, self.config.tuning.max_request_bytes) {
                        self.send(&batch)?;
                        pacer.record(batch.records as u32);
                        records_in_shard += batch.records as u64;
                        bytes_in_shard += batch.body.len() as u64;
                    }

                    let Some(resume) = next else { break };

                    // Loki answering with entries at or before the cursor would otherwise re-fetch
                    // and re-send the same page forever.
                    if resume < cursor {
                        bail!(
                            "Loki returned entries before the requested start for {selector}; \
                             refusing to re-send the same page"
                        );
                    }
                    if resume == cursor && fresh.is_empty() {
                        bail!(
                            "Loki made no progress past {cursor} for {selector}; \
                             the page limit may be smaller than this client expects"
                        );
                    }

                    sent_at_cursor = fresh
                        .iter()
                        .filter(|entry| entry.timestamp_ns == resume)
                        .map(|entry| line_key(&entry.line))
                        .collect();
                    cursor = resume;
                }

                // Only after every batch in the window is acknowledged, so a crash re-sends this
                // shard rather than skipping it.
                let end = window
                    .end
                    .timestamp_nanos_opt()
                    .context("shard end is outside the nanosecond range")?;
                checkpoint.complete_shard(selector, end, records_in_shard, bytes_in_shard);
                checkpoint.save(self.checkpoint_path)?;
            }
        }

        println!(
            "Imported {} records ({} bytes sent). Checkpoint: {}",
            checkpoint.records_sent,
            checkpoint.bytes_sent,
            self.checkpoint_path.display()
        );
        Ok(())
    }

    fn send(&self, batch: &Batch) -> Result<()> {
        for attempt in 0..MAX_ATTEMPTS {
            let response = self
                .http
                .post(&self.intake_url)
                .header("Content-Type", "application/json")
                .bearer_auth(&self.project_key)
                .body(batch.body.clone())
                .send()
                .context("failed to reach the PostHog logs intake")?;

            let retry_after = response
                .headers()
                .get(reqwest::header::RETRY_AFTER)
                .and_then(|value| value.to_str().ok())
                .map(str::to_string);

            match classify(response.status(), retry_after.as_deref(), attempt) {
                Disposition::Accepted => return Ok(()),
                Disposition::Permanent(message) => bail!(message),
                Disposition::Retry(wait) => {
                    eprintln!(
                        "intake asked to wait {}s (attempt {}/{MAX_ATTEMPTS})",
                        wait.as_secs(),
                        attempt + 1
                    );
                    sleep(wait);
                }
            }
        }

        bail!("gave up after {MAX_ATTEMPTS} attempts against the logs intake")
    }
}

/// The intake route, carrying the backfill window the range needs.
pub fn intake_url(host: &str, from: chrono::DateTime<chrono::Utc>) -> String {
    let days = (chrono::Utc::now() - from).num_days().max(1) + 1;
    format!(
        "{}/i/v1/logs?backfill_days={days}",
        host.trim_end_matches('/')
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{Duration, Utc};

    #[test]
    fn the_backfill_window_covers_the_oldest_record_in_the_range() {
        // Asking for exactly the age of the oldest record loses it to rounding, so the window is
        // one day wider than the range's age.
        let from = Utc::now() - Duration::days(540);

        let url = intake_url("https://us.i.posthog.com", from);

        assert!(url.contains("backfill_days=541"), "got {url}");
    }

    #[test]
    fn a_trailing_slash_on_the_host_does_not_double_up() {
        let url = intake_url("https://us.i.posthog.com/", Utc::now() - Duration::days(1));

        assert!(
            url.starts_with("https://us.i.posthog.com/i/v1/logs?"),
            "got {url}"
        );
    }

    #[test]
    fn a_missing_project_key_says_which_variable_to_set_and_why() {
        temp_unset(PROJECT_KEY_VAR);

        let error = project_key_from_env().expect_err("must not run without a project key");

        let rendered = format!("{error:#}");
        assert!(rendered.contains(PROJECT_KEY_VAR), "got {rendered}");
        assert!(rendered.contains("personal API token"), "got {rendered}");
    }

    fn temp_unset(key: &str) {
        // Safe here: the tests in this module do not read this variable concurrently.
        unsafe { std::env::remove_var(key) };
    }
}
