use std::fmt::Write as _;

use chrono::{DateTime, Utc};

use super::config::LokiImportConfig;
use super::mapping::MappingHits;

/// What a run will do, computed before it moves any data.
#[derive(Debug, Clone, PartialEq)]
pub struct RunPlan {
    pub shards: u64,
    pub bytes: u64,
    pub seconds: u64,
}

impl RunPlan {
    /// `sample_records` and `sample_bytes` come from the dry run's sample, and scale the reported
    /// volume into a record count. Using the sample count as the workload would report the time to
    /// send a hundred records, which is about a second for any run.
    pub fn build(
        config: &LokiImportConfig,
        volume_bytes: u64,
        sample_records: u64,
        sample_bytes: u64,
    ) -> Self {
        let span = (config.range.to - config.range.from).num_seconds().max(0) as u64;
        let shard = config.tuning.shard.seconds().max(1);
        let shards = span.div_ceil(shard) * config.range.select.len() as u64;
        let rate = u64::from(config.tuning.max_records_per_second.get());

        let bytes_per_record = sample_bytes.checked_div(sample_records).unwrap_or(0);
        let total_records = volume_bytes
            .checked_div(bytes_per_record.max(1))
            .unwrap_or(0);

        Self {
            shards,
            bytes: volume_bytes,
            seconds: if bytes_per_record == 0 {
                0
            } else {
                total_records.div_ceil(rate)
            },
        }
    }
}

/// The report `--dry-run` prints. A change-control process approves a run from this, so it states
/// the cost before the run and the mapping coverage that decides whether the data will be usable.
pub fn render(
    config: &LokiImportConfig,
    plan: &RunPlan,
    hits: &MappingHits,
    samples: &[(&str, Option<String>)],
) -> String {
    let mut out = String::new();

    let _ = writeln!(out, "Source      {}", config.source.url);
    if let Some(tenant) = &config.source.tenant {
        let _ = writeln!(out, "Tenant      {tenant}");
    }
    let _ = writeln!(
        out,
        "Range       {} to {}  ({} days, {} shards)",
        day(config.range.from),
        day(config.range.to),
        (config.range.to - config.range.from).num_days(),
        plan.shards
    );
    let _ = writeln!(
        out,
        "Volume      {} across {} selector(s)",
        human_bytes(plan.bytes),
        config.range.select.len()
    );
    let _ = writeln!(
        out,
        "Estimated   {} at {} records/sec, {} egress",
        human_duration(plan.seconds),
        config.tuning.max_records_per_second,
        human_bytes(plan.bytes)
    );
    let _ = writeln!(out);
    let _ = writeln!(out, "Mapping, from {} sampled records:", hits.total);

    for (field, example) in samples {
        let matched = match *field {
            "service_name" => hits.service_name,
            "severity" => hits.severity,
            "trace_id" => hits.trace_id,
            "span_id" => hits.span_id,
            _ => 0,
        };
        let detail = match example {
            Some(value) if matched > 0 => format!("e.g. {value:?}"),
            _ => "NOT FOUND, no record carried this field".to_string(),
        };
        let _ = writeln!(out, "  {field:<16}{matched:>4}/{:<4}  {detail}", hits.total);
    }

    out
}

fn day(at: DateTime<Utc>) -> String {
    at.format("%Y-%m-%d").to_string()
}

fn human_bytes(bytes: u64) -> String {
    const UNITS: [&str; 5] = ["B", "KB", "MB", "GB", "TB"];
    let mut value = bytes as f64;
    let mut unit = 0;
    while value >= 1024.0 && unit < UNITS.len() - 1 {
        value /= 1024.0;
        unit += 1;
    }
    if unit == 0 {
        format!("{bytes} B")
    } else {
        format!("{value:.1} {}", UNITS[unit])
    }
}

fn human_duration(seconds: u64) -> String {
    match seconds {
        0..=59 => format!("{seconds}s"),
        60..=3599 => format!("{}m", seconds / 60),
        _ => format!("{}h{:02}m", seconds / 3600, (seconds % 3600) / 60),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::experimental::logs::config::LokiImportConfig;

    fn config(select: &str, shard: &str) -> LokiImportConfig {
        LokiImportConfig::parse(&format!(
            r#"
version: 1
source: {{ url: https://loki.example.com }}
range:
  from: 2025-03-01T00:00:00Z
  to: 2025-03-03T00:00:00Z
  select: [{select}]
extract:
  service_name: {{ type: label, name: app }}
tuning:
  shard: {shard}
"#
        ))
        .expect("valid config")
    }

    #[test]
    fn shard_count_covers_every_selector_and_rounds_up() {
        // Two days at 6h is 8 shards per selector; a partial shard still has to run.
        let two_selectors = RunPlan::build(&config("'{a=\"1\"}', '{b=\"2\"}'", "6h"), 0, 0, 0);
        let uneven = RunPlan::build(&config("'{a=\"1\"}'", "5h"), 0, 0, 0);

        assert_eq!(two_selectors.shards, 16);
        assert_eq!(uneven.shards, 10, "48h at 5h must round up to 10, not 9");
    }

    #[test]
    fn a_field_that_matched_nothing_reads_as_not_found() {
        // This line is why --dry-run exists: it is the only warning before a multi-hour run that
        // an extraction rule will produce nothing.
        let hits = MappingHits {
            total: 100,
            service_name: 100,
            severity: 94,
            trace_id: 0,
            span_id: 0,
        };
        let samples = [
            ("service_name", Some("checkout-api".to_string())),
            ("severity", Some("error".to_string())),
            ("trace_id", None),
        ];

        let report = render(
            &config("'{a=\"1\"}'", "1h"),
            &RunPlan::build(&config("'{a=\"1\"}'", "1h"), 0, 0, 0),
            &hits,
            &samples,
        );

        assert!(
            report.contains("service_name     100/100"),
            "got:\n{report}"
        );
        assert!(report.contains("trace_id"), "got:\n{report}");
        assert!(report.contains("NOT FOUND"), "got:\n{report}");
    }

    #[test]
    fn sizes_and_durations_render_in_units_a_person_reads() {
        for (bytes, expected) in [
            (512u64, "512 B"),
            (2048, "2.0 KB"),
            (2_600_000_000_000, "2.4 TB"),
        ] {
            assert_eq!(human_bytes(bytes), expected);
        }
        for (seconds, expected) in [(45u64, "45s"), (900, "15m"), (50_400, "14h00m")] {
            assert_eq!(human_duration(seconds), expected);
        }
    }
}
