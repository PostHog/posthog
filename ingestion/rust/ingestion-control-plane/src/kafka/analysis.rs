use std::collections::HashMap;

use common_types::CapturedEventHeaders;
use hdrhistogram::Histogram;
use serde::Serialize;

/// Cap on tracked token cardinality; messages for tokens beyond it are
/// counted in `token_overflow`.
const MAX_TRACKED_TOKENS: usize = 1_000;

/// Global cap on tracked distinct_id cardinality (across all tokens); beyond
/// it new ids are counted in the owning token's `distinct_id_overflow` so a
/// pathological partition can't balloon memory.
const MAX_TRACKED_DISTINCT_IDS: usize = 50_000;

/// Cumulative size-histogram bucket boundaries (bytes).
const SIZE_BUCKETS: &[u64] = &[
    256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216,
];

/// How many events / distinct_ids to report per token.
const NESTED_TOP_K: usize = 10;

#[derive(Debug, Clone, Serialize)]
pub struct KeyCount {
    pub key: String,
    pub count: u64,
    /// Percentage relative to the owning token's messages.
    pub pct: f64,
}

/// Per-token (i.e. per-team) breakdown: events and distinct_ids are only
/// meaningful within a token, so they are nested here rather than reported
/// globally.
#[derive(Debug, Clone, Serialize)]
pub struct TokenBreakdown {
    pub token: String,
    pub team_id: Option<i32>,
    pub count: u64,
    /// Percentage relative to all analyzed messages.
    pub pct: f64,
    pub total_bytes: u64,
    pub top_events: Vec<KeyCount>,
    pub top_distinct_ids: Vec<KeyCount>,
    pub distinct_ids_tracked: u64,
    pub distinct_id_overflow: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SizeBucket {
    pub le: u64,
    pub count: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct SizeStats {
    pub count: u64,
    pub min: u64,
    pub max: u64,
    pub mean: f64,
    pub p50: u64,
    pub p90: u64,
    pub p99: u64,
    pub total_bytes: u64,
    pub histogram: Vec<SizeBucket>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct FlagCounts {
    pub historical_migration: u64,
    pub force_disable_person_processing: u64,
    pub missing_headers: u64,
    pub missing_token: u64,
}

/// Aggregates produced by one analysis run. `team_id` on tokens is filled in
/// afterwards by the token resolver.
#[derive(Debug, Clone, Serialize)]
pub struct Aggregates {
    pub messages: u64,
    pub top_tokens: Vec<TokenBreakdown>,
    pub tokens_tracked: u64,
    /// Messages whose token was beyond the tracked-token cap.
    pub token_overflow: u64,
    pub sizes: SizeStats,
    pub flags: FlagCounts,
}

#[derive(Default)]
struct TokenAgg {
    count: u64,
    total_bytes: u64,
    events: HashMap<String, u64>,
    distinct_ids: HashMap<String, u64>,
    distinct_id_overflow: u64,
}

/// Incremental, header-only aggregation over a partition's messages.
/// Pure data structure: feed it `(headers, payload_size)` pairs and call
/// [`Aggregator::finish`].
pub struct Aggregator {
    messages: u64,
    tokens: HashMap<String, TokenAgg>,
    token_overflow: u64,
    tracked_distinct_ids: usize,
    sizes: Histogram<u64>,
    total_bytes: u64,
    flags: FlagCounts,
}

impl Default for Aggregator {
    fn default() -> Self {
        Self::new()
    }
}

impl Aggregator {
    pub fn new() -> Self {
        let mut sizes = Histogram::new(3).expect("3 significant figures is always valid");
        sizes.auto(true);
        Self {
            messages: 0,
            tokens: HashMap::new(),
            token_overflow: 0,
            tracked_distinct_ids: 0,
            sizes,
            total_bytes: 0,
            flags: FlagCounts::default(),
        }
    }

    pub fn record(&mut self, headers: Option<&CapturedEventHeaders>, payload_size: u64) {
        self.messages += 1;
        self.total_bytes += payload_size;
        // Values beyond the auto-resized range cannot fail to record.
        self.sizes.record(payload_size).ok();

        let Some(headers) = headers else {
            self.flags.missing_headers += 1;
            return;
        };

        if headers.historical_migration == Some(true) {
            self.flags.historical_migration += 1;
        }
        if headers.force_disable_person_processing == Some(true) {
            self.flags.force_disable_person_processing += 1;
        }

        let Some(token) = &headers.token else {
            self.flags.missing_token += 1;
            return;
        };

        if self.tokens.len() >= MAX_TRACKED_TOKENS && !self.tokens.contains_key(token) {
            self.token_overflow += 1;
            return;
        }
        let token_agg = self.tokens.entry(token.clone()).or_default();
        token_agg.count += 1;
        token_agg.total_bytes += payload_size;

        if let Some(event) = &headers.event {
            *token_agg.events.entry(event.clone()).or_default() += 1;
        }
        if let Some(distinct_id) = &headers.distinct_id {
            if token_agg.distinct_ids.contains_key(distinct_id) {
                *token_agg
                    .distinct_ids
                    .entry(distinct_id.clone())
                    .or_default() += 1;
            } else if self.tracked_distinct_ids < MAX_TRACKED_DISTINCT_IDS {
                token_agg.distinct_ids.insert(distinct_id.clone(), 1);
                self.tracked_distinct_ids += 1;
            } else {
                token_agg.distinct_id_overflow += 1;
            }
        }
    }

    pub fn finish(self, top_k: usize) -> Aggregates {
        let messages = self.messages;
        let overall_pct = |count: u64| {
            if messages == 0 {
                0.0
            } else {
                (count as f64 / messages as f64) * 100.0
            }
        };

        let mut histogram = Vec::with_capacity(SIZE_BUCKETS.len());
        for &le in SIZE_BUCKETS {
            histogram.push(SizeBucket {
                le,
                count: self.sizes.count_between(0, le),
            });
        }

        // Zero out stats for an empty analysis (e.g. a committed offset
        // already at the high watermark) rather than deriving them from an
        // empty histogram.
        let sizes = if self.sizes.is_empty() {
            SizeStats {
                count: 0,
                min: 0,
                max: 0,
                mean: 0.0,
                p50: 0,
                p90: 0,
                p99: 0,
                total_bytes: self.total_bytes,
                histogram,
            }
        } else {
            SizeStats {
                count: self.sizes.len(),
                min: self.sizes.min(),
                max: self.sizes.max(),
                mean: self.sizes.mean(),
                p50: self.sizes.value_at_quantile(0.5),
                p90: self.sizes.value_at_quantile(0.9),
                p99: self.sizes.value_at_quantile(0.99),
                total_bytes: self.total_bytes,
                histogram,
            }
        };

        let tokens_tracked = self.tokens.len() as u64;
        let mut entries: Vec<(String, TokenAgg)> = self.tokens.into_iter().collect();
        entries.sort_by(|a, b| b.1.count.cmp(&a.1.count).then_with(|| a.0.cmp(&b.0)));

        let top_tokens = entries
            .into_iter()
            .take(top_k)
            .map(|(token, agg)| {
                let token_pct = |count: u64| {
                    if agg.count == 0 {
                        0.0
                    } else {
                        (count as f64 / agg.count as f64) * 100.0
                    }
                };
                let distinct_ids_tracked = agg.distinct_ids.len() as u64;
                TokenBreakdown {
                    token,
                    team_id: None,
                    count: agg.count,
                    pct: overall_pct(agg.count),
                    total_bytes: agg.total_bytes,
                    top_events: top_counts(agg.events, NESTED_TOP_K, token_pct),
                    top_distinct_ids: top_counts(agg.distinct_ids, NESTED_TOP_K, token_pct),
                    distinct_ids_tracked,
                    distinct_id_overflow: agg.distinct_id_overflow,
                }
            })
            .collect();

        Aggregates {
            messages,
            top_tokens,
            tokens_tracked,
            token_overflow: self.token_overflow,
            sizes,
            flags: self.flags,
        }
    }
}

fn top_counts(
    counts: HashMap<String, u64>,
    top_k: usize,
    pct: impl Fn(u64) -> f64,
) -> Vec<KeyCount> {
    let mut entries: Vec<(String, u64)> = counts.into_iter().collect();
    entries.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    entries
        .into_iter()
        .take(top_k)
        .map(|(key, count)| KeyCount {
            key,
            count,
            pct: pct(count),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn headers(token: &str, distinct_id: &str, event: &str) -> CapturedEventHeaders {
        CapturedEventHeaders {
            token: Some(token.to_string()),
            distinct_id: Some(distinct_id.to_string()),
            session_id: None,
            timestamp: None,
            event: Some(event.to_string()),
            uuid: None,
            now: None,
            force_disable_person_processing: None,
            historical_migration: None,
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        }
    }

    #[test]
    fn nests_events_and_distinct_ids_per_token() {
        let mut agg = Aggregator::new();
        for _ in 0..6 {
            agg.record(Some(&headers("token_a", "user_hot", "$pageview")), 100);
        }
        agg.record(Some(&headers("token_a", "user_other", "$identify")), 100);
        for _ in 0..3 {
            agg.record(Some(&headers("token_b", "user_b", "$identify")), 1000);
        }
        let result = agg.finish(10);

        assert_eq!(result.messages, 10);
        assert_eq!(result.top_tokens.len(), 2);

        let a = &result.top_tokens[0];
        assert_eq!(a.token, "token_a");
        assert_eq!(a.count, 7);
        assert!((a.pct - 70.0).abs() < f64::EPSILON);
        assert_eq!(a.total_bytes, 700);
        assert_eq!(a.top_events[0].key, "$pageview");
        assert_eq!(a.top_events[0].count, 6);
        // Nested pct is relative to the token, not all messages.
        assert!((a.top_events[0].pct - (6.0 / 7.0 * 100.0)).abs() < 0.001);
        assert_eq!(a.top_distinct_ids[0].key, "user_hot");

        let b = &result.top_tokens[1];
        assert_eq!(b.token, "token_b");
        assert_eq!(b.top_events[0].key, "$identify");
        assert!((b.top_events[0].pct - 100.0).abs() < f64::EPSILON);
    }

    #[test]
    fn respects_top_k_for_tokens() {
        let mut agg = Aggregator::new();
        for i in 0..20 {
            agg.record(Some(&headers(&format!("token_{i}"), "d", "e")), 10);
        }
        let result = agg.finish(5);
        assert_eq!(result.top_tokens.len(), 5);
        assert_eq!(result.tokens_tracked, 20);
    }

    #[test]
    fn counts_missing_headers_and_flags() {
        let mut agg = Aggregator::new();
        agg.record(None, 50);
        let mut h = headers("t", "d", "e");
        h.historical_migration = Some(true);
        h.force_disable_person_processing = Some(true);
        agg.record(Some(&h), 60);
        let mut no_token = headers("t", "d", "e");
        no_token.token = None;
        agg.record(Some(&no_token), 70);

        let result = agg.finish(10);
        assert_eq!(result.flags.missing_headers, 1);
        assert_eq!(result.flags.historical_migration, 1);
        assert_eq!(result.flags.force_disable_person_processing, 1);
        assert_eq!(result.flags.missing_token, 1);
    }

    #[test]
    fn size_histogram_buckets_are_cumulative() {
        let mut agg = Aggregator::new();
        agg.record(None, 100);
        agg.record(None, 2000);
        agg.record(None, 2_000_000);
        let result = agg.finish(10);

        let bucket = |le: u64| {
            result
                .sizes
                .histogram
                .iter()
                .find(|b| b.le == le)
                .unwrap()
                .count
        };
        assert_eq!(bucket(256), 1);
        assert_eq!(bucket(4096), 2);
        assert_eq!(bucket(16777216), 3);
    }

    #[test]
    fn empty_aggregation_is_well_formed() {
        let result = Aggregator::new().finish(10);
        assert_eq!(result.messages, 0);
        assert_eq!(result.sizes.count, 0);
        assert_eq!(result.sizes.mean, 0.0);
        assert_eq!(result.sizes.p99, 0);
        assert!(result.top_tokens.is_empty());
        // The result must stay JSON-serializable (no NaN from empty stats).
        assert!(serde_json::to_string(&result).is_ok());
    }
}
