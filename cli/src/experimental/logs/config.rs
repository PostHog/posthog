use std::collections::HashMap;
use std::num::NonZeroU32;

use anyhow::{bail, Context, Result};
use chrono::{DateTime, TimeZone, Utc};
use regex::Regex;
use serde::{Deserialize, Deserializer};
use url::Url;

/// Where one OTel field comes from in a Loki record.
#[derive(Debug, Clone, Deserialize, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Extractor {
    Label { name: String },
    StructuredMetadata { key: String },
    JsonField { path: String },
    Regex { pattern: String, group: usize },
    Literal { value: String },
}

impl Extractor {
    fn validate(&self) -> Result<()> {
        if let Extractor::Regex { pattern, group } = self {
            let compiled = Regex::new(pattern)
                .with_context(|| format!("regex extractor has an invalid pattern: {pattern}"))?;
            if *group == 0 {
                bail!(
                    "regex extractor group must be 1 or higher, because group 0 is the whole match"
                );
            }
            if *group >= compiled.captures_len() {
                bail!(
                    "regex extractor asks for group {group} but the pattern has {} capture groups",
                    compiled.captures_len().saturating_sub(1)
                );
            }
        }
        Ok(())
    }
}

/// One extractor, or an ordered list where the first that yields a value wins.
#[derive(Debug, Clone, PartialEq)]
pub struct Extractors(Vec<Extractor>);

/// Dispatches on the YAML node kind rather than deriving `untagged`, which discards the inner
/// error and turns a misspelled key into "data did not match any variant".
impl<'de> Deserialize<'de> for Extractors {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        use serde::de::Error;

        let value = serde_yaml::Value::deserialize(deserializer)?;
        let extractors = if value.is_sequence() {
            Vec::<Extractor>::deserialize(value).map_err(D::Error::custom)?
        } else {
            vec![Extractor::deserialize(value).map_err(D::Error::custom)?]
        };
        Ok(Extractors(extractors))
    }
}

impl Extractors {
    pub fn as_slice(&self) -> &[Extractor] {
        &self.0
    }

    fn validate(&self) -> Result<()> {
        if self.0.is_empty() {
            bail!("an extractor list cannot be empty");
        }
        for extractor in &self.0 {
            extractor.validate()?;
        }
        Ok(())
    }
}

/// A shard width, stored as the seconds it parsed to so no consumer re-parses the string.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Shard(u64);

impl Shard {
    pub fn seconds(self) -> u64 {
        self.0
    }
}

impl Default for Shard {
    fn default() -> Self {
        Shard(3600)
    }
}

impl<'de> Deserialize<'de> for Shard {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = String::deserialize(deserializer)?;
        parse_shard(&raw)
            .map(Shard)
            .map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Source {
    pub url: Url,
    #[serde(default)]
    pub tenant: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Range {
    pub from: DateTime<Utc>,
    pub to: DateTime<Utc>,
    pub select: Vec<String>,
}

impl Range {
    fn validate(&self) -> Result<()> {
        if self.from >= self.to {
            bail!("range.from must be earlier than range.to");
        }
        // Loki's query_range speaks nanosecond epochs, which chrono can only represent between
        // 1677 and 2262. A range outside that turns into a silently wrong query.
        let floor = Utc.with_ymd_and_hms(1970, 1, 1, 0, 0, 0).unwrap();
        let ceiling = Utc::now() + chrono::Duration::days(1);
        if self.from < floor {
            bail!("range.from must be 1970-01-01 or later");
        }
        if self.to > ceiling {
            bail!("range.to must not be more than a day in the future");
        }
        if self.select.is_empty() {
            bail!(
                "range.select needs at least one stream selector; LogQL rejects an empty matcher"
            );
        }
        if let Some(position) = self.select.iter().position(|s| s.trim().is_empty()) {
            bail!("range.select[{position}] is empty; LogQL rejects an empty matcher");
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Extract {
    pub service_name: Extractors,
    #[serde(default)]
    pub severity: Option<Extractors>,
    #[serde(default)]
    pub trace_id: Option<Extractors>,
    #[serde(default)]
    pub span_id: Option<Extractors>,
    /// Labels promoted to resource attributes. Every other label becomes a per-record attribute.
    /// Absent means every label is a resource attribute, which is the Loki-faithful reading.
    #[serde(default)]
    pub resource_labels: Option<Vec<String>>,
    #[serde(default)]
    pub extra_attributes: HashMap<String, Extractors>,
}

impl Extract {
    fn validate(&self) -> Result<()> {
        let named = [
            ("service_name", Some(&self.service_name)),
            ("severity", self.severity.as_ref()),
            ("trace_id", self.trace_id.as_ref()),
            ("span_id", self.span_id.as_ref()),
        ];
        for (field, extractors) in named {
            if let Some(extractors) = extractors {
                extractors
                    .validate()
                    .with_context(|| format!("extract.{field} is invalid"))?;
            }
        }
        for (name, extractors) in &self.extra_attributes {
            extractors
                .validate()
                .with_context(|| format!("extract.extra_attributes.{name} is invalid"))?;
        }
        if self.resource_labels.as_ref().is_some_and(|l| l.is_empty()) {
            bail!(
                "extract.resource_labels is an empty list, which promotes no labels at all. \
                 Remove the key to promote every label instead."
            );
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Tuning {
    pub shard: Shard,
    pub max_records_per_second: NonZeroU32,
    /// Must stay under the intake's `MAX_REQUEST_BODY_SIZE_BYTES`. The Rust default is 2 MiB but
    /// PostHog Cloud raises it, so this is configurable rather than a constant.
    pub max_request_bytes: usize,
}

/// The intake rejects a larger body with 413, and no batching can recover from that.
const MAX_SUPPORTED_REQUEST_BYTES: usize = 10 * 1024 * 1024;

impl Default for Tuning {
    fn default() -> Self {
        Self {
            shard: Shard::default(),
            max_records_per_second: NonZeroU32::new(20_000).expect("20000 is not zero"),
            max_request_bytes: 1_500_000,
        }
    }
}

impl Tuning {
    fn validate(&self) -> Result<()> {
        if self.max_request_bytes < 64 * 1024 {
            bail!("tuning.max_request_bytes must be at least 65536, or no batch can be filled");
        }
        if self.max_request_bytes > MAX_SUPPORTED_REQUEST_BYTES {
            bail!(
                "tuning.max_request_bytes {} is above {MAX_SUPPORTED_REQUEST_BYTES}; the intake \
                 answers a larger body with 413",
                self.max_request_bytes
            );
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LokiImportConfig {
    pub version: u32,
    pub source: Source,
    pub range: Range,
    pub extract: Extract,
    #[serde(default)]
    pub tuning: Tuning,
}

/// Read only the version, so a future config reports its version rather than the first field this
/// build does not recognize.
#[derive(Deserialize)]
struct VersionProbe {
    version: u32,
}

impl LokiImportConfig {
    pub fn parse(yaml: &str) -> Result<Self> {
        if let Ok(probe) = serde_yaml::from_str::<VersionProbe>(yaml) {
            if probe.version != 1 {
                bail!("unsupported config version {}, expected 1", probe.version);
            }
        }

        let config: Self =
            serde_yaml::from_str(yaml).context("failed to parse the import config")?;
        config.validate()?;
        Ok(config)
    }

    fn validate(&self) -> Result<()> {
        if self.version != 1 {
            bail!("unsupported config version {}, expected 1", self.version);
        }
        self.range.validate()?;
        self.extract.validate()?;
        self.tuning.validate()
    }
}

/// Parses a shard width such as `30m`, `1h` or `6h` into seconds.
fn parse_shard(shard: &str) -> Result<u64> {
    let split = shard
        .find(|c: char| !c.is_ascii_digit())
        .unwrap_or(shard.len());
    let (value, unit) = shard.split_at(split);
    let value: u64 = value.parse().with_context(|| {
        format!("shard '{shard}' must start with a number of seconds, minutes or hours")
    })?;
    if value == 0 {
        bail!("shard must be longer than zero");
    }
    let per_unit = match unit {
        "s" => 1,
        "m" => 60,
        "h" => 3600,
        _ => bail!("shard '{shard}' must end in s, m or h"),
    };
    let seconds = value
        .checked_mul(per_unit)
        .with_context(|| format!("shard '{shard}' is too large to express in seconds"))?;
    // Loki's max_query_length defaults to 721h, and a shard is issued as one query_range call.
    if seconds > 24 * 3600 {
        bail!("shard '{shard}' is over 24h, which risks Loki's max_query_length limit");
    }
    Ok(seconds)
}

#[cfg(test)]
mod tests {
    use super::*;

    const FULL: &str = r#"
version: 1
source:
  url: https://loki.example.com
  tenant: prod
range:
  from: 2025-03-01T00:00:00Z
  to: 2026-09-01T00:00:00Z
  select:
    - '{namespace="prod"}'
extract:
  service_name: { type: label, name: app }
  severity:
    - { type: json_field, path: level }
    - { type: label, name: level }
  resource_labels: [namespace, app]
tuning:
  shard: 1h
"#;

    #[test]
    fn parses_a_full_config() {
        let config = LokiImportConfig::parse(FULL).expect("valid");

        assert_eq!(
            config.extract.service_name.as_slice(),
            [Extractor::Label {
                name: "app".to_string()
            }]
        );
        assert_eq!(config.extract.severity.unwrap().as_slice().len(), 2);
        assert_eq!(config.tuning.shard.seconds(), 3600);
        assert_eq!(config.tuning.max_request_bytes, 1_500_000);
    }

    #[test]
    fn rejects_configs_that_would_fail_hours_into_a_run() {
        // (case, yaml patch applied to FULL, expected substring of the error)
        let cases = [
            (
                "an unknown key",
                FULL.replace("shard: 1h", "shard: 1h\n  concurency: 4"),
                "unknown field",
            ),
            (
                "a typo inside an extractor, which must name the field",
                FULL.replace("{ type: label, name: app }", "{ type: label, nmae: app }"),
                "nmae",
            ),
            (
                "a misspelled extractor type",
                FULL.replace("{ type: label, name: app }", "{ type: labl, name: app }"),
                "labl",
            ),
            (
                "a reversed range",
                FULL.replace("from: 2025-03-01T00:00:00Z", "from: 2027-03-01T00:00:00Z"),
                "earlier than",
            ),
            (
                "a range reaching past what Loki nanosecond epochs express",
                FULL.replace("to: 2026-09-01T00:00:00Z", "to: 2099-01-01T00:00:00Z"),
                "day in the future",
            ),
            (
                "an empty selector list",
                FULL.replace("    - '{namespace=\"prod\"}'\n", ""),
                "at least one stream selector",
            ),
            (
                "a blank selector inside the list",
                FULL.replace("'{namespace=\"prod\"}'", "''"),
                "is empty",
            ),
            (
                "a malformed source url",
                FULL.replace("https://loki.example.com", "loki.example.com"),
                "relative URL",
            ),
            (
                "an uncompilable regex",
                FULL.replace(
                    "{ type: label, name: app }",
                    "{ type: regex, pattern: '([unclosed', group: 1 }",
                ),
                "invalid pattern",
            ),
            (
                "a regex group the pattern does not have",
                FULL.replace(
                    "{ type: label, name: app }",
                    "{ type: regex, pattern: '(\\w+)', group: 4 }",
                ),
                "capture groups",
            ),
            (
                "a shard that overflows on the unit multiply",
                FULL.replace("shard: 1h", "shard: 1152921504606846977h"),
                "too large",
            ),
            (
                "a shard wider than Loki will answer",
                FULL.replace("shard: 1h", "shard: 48h"),
                "over 24h",
            ),
            (
                "a shard with no unit",
                FULL.replace("shard: 1h", "shard: '90'"),
                "must end in",
            ),
            (
                "a zero shard",
                FULL.replace("shard: 1h", "shard: 0h"),
                "longer than zero",
            ),
            (
                "a body size the intake answers with 413",
                FULL.replace("shard: 1h", "shard: 1h\n  max_request_bytes: 50000000"),
                "413",
            ),
            (
                "a body size no batch can fill",
                FULL.replace("shard: 1h", "shard: 1h\n  max_request_bytes: 1024"),
                "at least",
            ),
            (
                "an empty resource_labels list, which means the opposite of absent",
                FULL.replace("resource_labels: [namespace, app]", "resource_labels: []"),
                "empty list",
            ),
            (
                "a future config version",
                FULL.replace("version: 1", "version: 2"),
                "unsupported config version",
            ),
        ];

        for (case, yaml, expected) in cases {
            let error = LokiImportConfig::parse(&yaml).unwrap_err_or_else_case(case);
            let rendered = format!("{error:#}");
            assert!(
                rendered.contains(expected),
                "{case}: expected an error mentioning '{expected}', got: {rendered}"
            );
        }
    }

    trait ExpectErrCase {
        fn unwrap_err_or_else_case(self, case: &str) -> anyhow::Error;
    }

    impl ExpectErrCase for Result<LokiImportConfig> {
        fn unwrap_err_or_else_case(self, case: &str) -> anyhow::Error {
            match self {
                Ok(_) => panic!("{case}: expected the config to be rejected, but it parsed"),
                Err(error) => error,
            }
        }
    }

    #[test]
    fn severity_accepts_one_extractor_or_a_list() {
        const SINGLE: &str = r#"
version: 1
source: { url: https://loki.example.com }
range:
  from: 2025-03-01T00:00:00Z
  to: 2026-09-01T00:00:00Z
  select: ['{namespace="prod"}']
extract:
  service_name: { type: label, name: app }
  severity: { type: label, name: level }
"#;

        let config = LokiImportConfig::parse(SINGLE).expect("valid");

        assert_eq!(config.extract.severity.unwrap().as_slice().len(), 1);
        assert_eq!(config.tuning.shard.seconds(), 3600);
    }

    #[test]
    fn parse_shard_converts_units() {
        assert_eq!(parse_shard("30s").unwrap(), 30);
        assert_eq!(parse_shard("15m").unwrap(), 900);
        assert_eq!(parse_shard("6h").unwrap(), 21600);
    }
}
