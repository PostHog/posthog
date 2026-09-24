use std::collections::HashSet;
use std::path::Path;
use std::thread::sleep;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use reqwest::blocking::Client;

use super::checkpoint::Checkpoint;
use super::config::LokiImportConfig;
use super::emit::{batch_records, Batch};
use super::loki::{Entry, LokiClient};
use super::mapping::Mapper;
use super::send::{backoff, classify, Disposition};
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

/// Suppresses entries already sent at one instant, across however many pages that instant spans.
///
/// Loki truncates a page by entry count, so a timestamp holding more entries than a page is read
/// over several pages that all start at it. Forgetting the earlier pages re-sends them.
#[derive(Debug)]
struct BoundaryFilter {
    cursor: i64,
    sent: HashSet<u64>,
}

impl BoundaryFilter {
    fn new(cursor: i64) -> Self {
        Self {
            cursor,
            sent: HashSet::new(),
        }
    }

    fn cursor(&self) -> i64 {
        self.cursor
    }

    fn keep(&self, entry: &Entry) -> bool {
        entry.timestamp_ns != self.cursor || !self.sent.contains(&entry_key(entry))
    }

    /// Moves to the next page's start. Staying on the same instant accumulates; moving off it
    /// discards, so the set never grows past one timestamp's worth of entries.
    fn advance(&mut self, fresh: &[Entry], resume: i64) {
        let boundary = fresh
            .iter()
            .filter(|entry| entry.timestamp_ns == resume)
            .map(entry_key);

        if resume == self.cursor {
            self.sent.extend(boundary);
        } else {
            self.sent = boundary.collect();
            self.cursor = resume;
        }
    }
}

/// Cheap identity for one entry at a shared timestamp, so the boundary dedup set stays small.
///
/// Covers the stream labels as well as the line: two pods emitting the same line in the same
/// nanosecond are different records, and hashing the line alone would drop one of them.
fn entry_key(entry: &Entry) -> u64 {
    use std::hash::{Hash, Hasher};

    let mut labels: Vec<(&String, &String)> = entry.labels.iter().collect();
    labels.sort();

    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    labels.hash(&mut hasher);
    entry.line.hash(&mut hasher);
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
    resolve_project_key(std::env::var(PROJECT_KEY_VAR).ok())
}

/// Split from the environment read so the message can be tested without mutating process globals.
fn resolve_project_key(raw: Option<String>) -> Result<String> {
    match raw.filter(|key| !key.is_empty()) {
        Some(key) => Ok(key),
        None => bail!(
            "set {PROJECT_KEY_VAR} to the project API key for the project you are importing into. \
             The intake rejects a personal API token."
        ),
    }
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
                let cursor = window
                    .start
                    .timestamp_nanos_opt()
                    .context("shard start is outside the nanosecond range")?;
                let mut records_in_shard = 0u64;
                let mut bytes_in_shard = 0u64;
                let mut boundary = BoundaryFilter::new(cursor);

                loop {
                    let (entries, next) =
                        self.loki
                            .query_page(selector, boundary.cursor(), window.end)?;
                    if entries.is_empty() {
                        break;
                    }

                    let fresh: Vec<_> = entries
                        .into_iter()
                        .filter(|entry| boundary.keep(entry))
                        .collect();

                    let mapped: Vec<_> = fresh.iter().map(|e| self.mapper.map(e)).collect();
                    for batch in batch_records(&mapped, self.config.tuning.max_request_bytes) {
                        self.send(&batch)?;
                        pacer.record(batch.records as u32);
                        records_in_shard += batch.records as u64;
                        bytes_in_shard += batch.body.len() as u64;
                    }

                    let Some(resume) = next else { break };
                    let cursor = boundary.cursor();

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

                    boundary.advance(&fresh, resume);
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
        let mut last_transport_error = None;

        for attempt in 0..MAX_ATTEMPTS {
            let sent = self
                .http
                .post(&self.intake_url)
                .header("Content-Type", "application/json")
                .bearer_auth(&self.project_key)
                .body(batch.body.clone())
                .send();

            let disposition = match sent {
                Ok(response) => {
                    let retry_after = response
                        .headers()
                        .get(reqwest::header::RETRY_AFTER)
                        .and_then(|value| value.to_str().ok())
                        .map(str::to_string);
                    classify(response.status(), retry_after.as_deref(), attempt)
                }
                // A reset connection, a DNS blip or a client timeout is transient. Failing the
                // whole run on one costs a shard of duplicates when it restarts.
                Err(error) if error.is_timeout() || error.is_connect() => {
                    last_transport_error = Some(error.to_string());
                    Disposition::Retry(backoff(attempt))
                }
                Err(error) => return Err(error).context("failed to reach the PostHog logs intake"),
            };

            match disposition {
                Disposition::Accepted => return Ok(()),
                Disposition::Permanent(message) => bail!(message),
                Disposition::Retry(wait) => {
                    // Sleeping before giving up wastes up to five minutes on a doomed run.
                    if attempt + 1 == MAX_ATTEMPTS {
                        break;
                    }
                    eprintln!(
                        "retrying in {}s (attempt {}/{MAX_ATTEMPTS})",
                        wait.as_secs(),
                        attempt + 1
                    );
                    sleep(wait);
                }
            }
        }

        match last_transport_error {
            Some(error) => bail!(
                "gave up after {MAX_ATTEMPTS} attempts against the logs intake; last error: {error}"
            ),
            None => bail!("gave up after {MAX_ATTEMPTS} attempts against the logs intake"),
        }
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

    fn at(timestamp_ns: i64, line: &str, pod: &str) -> Entry {
        Entry {
            timestamp_ns,
            line: line.to_string(),
            structured_metadata: Default::default(),
            labels: std::collections::HashMap::from([("pod".to_string(), pod.to_string())]),
        }
    }

    #[test]
    fn an_instant_spanning_several_pages_never_resends_an_earlier_page() {
        // Loki truncates by entry count, so one timestamp can be read over several pages that all
        // start at it. Replacing the boundary set instead of extending it forgets page one, and
        // page three sends it again.
        let mut boundary = BoundaryFilter::new(100);
        let page_one = vec![at(100, "a", "p1"), at(100, "b", "p1")];
        boundary.advance(&page_one, 100);

        let page_two = vec![at(100, "c", "p1")];
        boundary.advance(&page_two, 100);

        assert!(
            !boundary.keep(&at(100, "a", "p1")),
            "page one must stay suppressed"
        );
        assert!(
            !boundary.keep(&at(100, "c", "p1")),
            "page two must stay suppressed"
        );
        assert!(
            boundary.keep(&at(100, "d", "p1")),
            "an unseen entry must pass"
        );
    }

    #[test]
    fn two_streams_emitting_the_same_line_at_one_instant_are_different_records() {
        // Hashing the line alone drops one of them, which is data loss rather than duplication.
        let mut boundary = BoundaryFilter::new(100);
        boundary.advance(&[at(100, "health check ok", "pod-a")], 100);

        assert!(!boundary.keep(&at(100, "health check ok", "pod-a")));
        assert!(boundary.keep(&at(100, "health check ok", "pod-b")));
    }

    #[test]
    fn moving_off_an_instant_forgets_it() {
        // Otherwise the set grows for the whole shard rather than one timestamp's worth.
        let mut boundary = BoundaryFilter::new(100);
        boundary.advance(&[at(100, "a", "p1")], 100);

        boundary.advance(&[at(200, "b", "p1")], 200);

        assert_eq!(boundary.cursor(), 200);
        assert!(
            boundary.keep(&at(100, "a", "p1")),
            "a past instant is no longer suppressed"
        );
        assert!(!boundary.keep(&at(200, "b", "p1")));
    }

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
        for (case, raw) in [("unset", None), ("set but empty", Some(String::new()))] {
            let error = resolve_project_key(raw).expect_err(case);

            let rendered = format!("{error:#}");
            assert!(rendered.contains(PROJECT_KEY_VAR), "{case}: {rendered}");
            assert!(
                rendered.contains("personal API token"),
                "{case}: {rendered}"
            );
        }
    }
}
