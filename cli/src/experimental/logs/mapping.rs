use std::collections::BTreeMap;

use regex::Regex;
use serde_json::Value as Json;

use super::config::{Extract, Extractor, Extractors};
use super::loki::Entry;

/// One Loki entry rendered into the fields an OTLP log record carries.
#[derive(Debug, Clone, PartialEq)]
pub struct MappedRecord {
    pub timestamp_ns: i64,
    pub body: String,
    pub service_name: Option<String>,
    pub severity: Option<(String, i32)>,
    pub trace_id: Option<String>,
    pub span_id: Option<String>,
    pub resource_attributes: BTreeMap<String, String>,
    pub attributes: BTreeMap<String, String>,
}

/// Which fields a mapping actually produced, counted over a sample so `--dry-run` can report a
/// rule that silently matches nothing.
#[derive(Debug, Default, Clone, PartialEq)]
pub struct MappingHits {
    pub total: usize,
    pub service_name: usize,
    pub severity: usize,
    pub trace_id: usize,
    pub span_id: usize,
}

pub struct Mapper {
    extract: Extract,
    compiled: Vec<Regex>,
}

impl Mapper {
    /// Compiles every regex extractor once. The config already proved they compile, so a failure
    /// here means the config was bypassed.
    pub fn new(extract: Extract) -> anyhow::Result<Self> {
        let mut compiled = Vec::new();
        for extractor in all_extractors(&extract) {
            if let Extractor::Regex { pattern, .. } = extractor {
                compiled.push(Regex::new(pattern)?);
            }
        }
        Ok(Self { extract, compiled })
    }

    pub fn map(&self, entry: &Entry) -> MappedRecord {
        let service_name = self.first_match(self.extract.service_name.as_slice(), entry);
        let severity = self
            .extract
            .severity
            .as_ref()
            .and_then(|e| self.first_match(e.as_slice(), entry))
            .map(|text| normalize_severity(&text));

        let (resource_attributes, mut attributes) = self.split_labels(entry);

        for (name, extractors) in &self.extract.extra_attributes {
            if let Some(value) = self.first_match(extractors.as_slice(), entry) {
                attributes.insert(name.clone(), value);
            }
        }

        MappedRecord {
            timestamp_ns: entry.timestamp_ns,
            body: entry.line.clone(),
            service_name,
            severity,
            trace_id: self
                .optional(self.extract.trace_id.as_ref(), entry)
                .and_then(|id| normalize_hex_id(&id, 32)),
            span_id: self
                .optional(self.extract.span_id.as_ref(), entry)
                .and_then(|id| normalize_hex_id(&id, 16)),
            resource_attributes,
            attributes,
        }
    }

    pub fn hits(&self, entries: &[Entry]) -> MappingHits {
        let mut hits = MappingHits {
            total: entries.len(),
            ..Default::default()
        };
        for entry in entries {
            let record = self.map(entry);
            hits.service_name += usize::from(record.service_name.is_some());
            hits.severity += usize::from(record.severity.is_some());
            hits.trace_id += usize::from(record.trace_id.is_some());
            hits.span_id += usize::from(record.span_id.is_some());
        }
        hits
    }

    fn optional(&self, extractors: Option<&Extractors>, entry: &Entry) -> Option<String> {
        self.first_match(extractors?.as_slice(), entry)
    }

    fn first_match(&self, extractors: &[Extractor], entry: &Entry) -> Option<String> {
        extractors
            .iter()
            .find_map(|extractor| self.evaluate(extractor, entry))
    }

    fn evaluate(&self, extractor: &Extractor, entry: &Entry) -> Option<String> {
        let found = match extractor {
            Extractor::Label { name } => entry.labels.get(name).cloned(),
            Extractor::StructuredMetadata { key } => entry.structured_metadata.get(key).cloned(),
            Extractor::JsonField { path } => json_field(&entry.line, path),
            Extractor::Regex { pattern, group } => self
                .compiled
                .iter()
                .find(|compiled| compiled.as_str() == pattern)
                .and_then(|compiled| compiled.captures(&entry.line))
                .and_then(|captures| captures.get(*group))
                .map(|matched| matched.as_str().to_string()),
            Extractor::Literal { value } => Some(value.clone()),
        };
        found.filter(|value| !value.is_empty())
    }

    /// Listed labels identify the resource, the rest ride on the record. Every label is a resource
    /// attribute when the key is absent, which is how Loki itself treats stream labels.
    fn split_labels(&self, entry: &Entry) -> (BTreeMap<String, String>, BTreeMap<String, String>) {
        let mut resource = BTreeMap::new();
        let mut attributes = BTreeMap::new();

        for (key, value) in &entry.labels {
            let is_resource = match &self.extract.resource_labels {
                None => true,
                Some(listed) => listed.iter().any(|name| name == key),
            };
            if is_resource {
                resource.insert(key.clone(), value.clone());
            } else {
                attributes.insert(key.clone(), value.clone());
            }
        }

        for (key, value) in &entry.structured_metadata {
            attributes.insert(key.clone(), value.clone());
        }

        (resource, attributes)
    }
}

fn all_extractors(extract: &Extract) -> impl Iterator<Item = &Extractor> {
    extract
        .service_name
        .as_slice()
        .iter()
        .chain(
            [
                extract.severity.as_ref(),
                extract.trace_id.as_ref(),
                extract.span_id.as_ref(),
            ]
            .into_iter()
            .flatten()
            .flat_map(|e| e.as_slice().iter()),
        )
        .chain(
            extract
                .extra_attributes
                .values()
                .flat_map(|e| e.as_slice().iter()),
        )
}

/// Reads a dotted path out of a JSON log line. A line that is not JSON yields nothing rather than
/// an error, because a stream usually mixes JSON and plain lines.
fn json_field(line: &str, path: &str) -> Option<String> {
    let mut current: &Json = &serde_json::from_str::<Json>(line).ok()?;
    for segment in path.split('.') {
        current = current.get(segment)?;
    }
    match current {
        Json::String(value) => Some(value.clone()),
        Json::Null => None,
        other => Some(other.to_string()),
    }
}

/// OTLP carries a trace id as 32 hex characters and a span id as 16. Anything else is dropped
/// rather than sent: the intake would either reject the batch, blaming an unrelated setting, or
/// store an id that joins to no span. Dashes are stripped so a UUID-shaped id still maps.
fn normalize_hex_id(raw: &str, expected: usize) -> Option<String> {
    let stripped: String = raw.chars().filter(|c| *c != '-').collect();
    let looks_hex = stripped.len() == expected && stripped.chars().all(|c| c.is_ascii_hexdigit());
    looks_hex.then(|| stripped.to_lowercase())
}

/// Mirrors `normalize_datadog_severity` in capture-logs, so a log imported here and a log sent
/// live land on the same severity number.
pub fn normalize_severity(text: &str) -> (String, i32) {
    match text.to_lowercase().as_str() {
        "emergency" | "emerg" | "critical" | "crit" | "alert" | "fatal" => {
            ("fatal".to_string(), 21)
        }
        "error" | "err" => ("error".to_string(), 17),
        "warning" | "warn" => ("warn".to_string(), 13),
        "notice" | "info" => ("info".to_string(), 9),
        "debug" => ("debug".to_string(), 5),
        "trace" => ("trace".to_string(), 1),
        _ => ("info".to_string(), 9),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::experimental::logs::config::LokiImportConfig;

    fn entry(line: &str, labels: &[(&str, &str)], metadata: &[(&str, &str)]) -> Entry {
        Entry {
            timestamp_ns: 1_700_000_000_000_000_000,
            line: line.to_string(),
            labels: labels
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
            structured_metadata: metadata
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
        }
    }

    fn mapper(extract_yaml: &str) -> Mapper {
        let yaml = format!(
            r#"
version: 1
source: {{ url: https://loki.example.com }}
range:
  from: 2025-03-01T00:00:00Z
  to: 2025-03-02T00:00:00Z
  select: ['{{namespace="prod"}}']
extract:
{extract_yaml}
"#
        );
        let config = LokiImportConfig::parse(&yaml).expect("valid config");
        Mapper::new(config.extract).expect("valid mapper")
    }

    #[test]
    fn severity_falls_through_the_list_in_order() {
        let mapper = mapper(
            "  service_name: { type: label, name: app }\n  \
             severity:\n    - { type: json_field, path: level }\n    - { type: label, name: level }",
        );

        let from_json = mapper.map(&entry(r#"{"level":"ERROR"}"#, &[("level", "info")], &[]));
        let from_label = mapper.map(&entry("plain text line", &[("level", "warn")], &[]));
        let neither = mapper.map(&entry("plain text line", &[], &[]));

        assert_eq!(from_json.severity, Some(("error".to_string(), 17)));
        assert_eq!(from_label.severity, Some(("warn".to_string(), 13)));
        assert_eq!(neither.severity, None);
    }

    #[test]
    fn resource_labels_decide_which_side_a_label_lands_on() {
        let listed = mapper(
            "  service_name: { type: label, name: app }\n  resource_labels: [app, namespace]",
        );
        let absent = mapper("  service_name: { type: label, name: app }");
        let record = entry("line", &[("app", "checkout"), ("pod", "checkout-abc")], &[]);

        let with_list = listed.map(&record);
        let without_list = absent.map(&record);

        assert!(with_list.resource_attributes.contains_key("app"));
        assert!(with_list.attributes.contains_key("pod"));
        assert!(without_list.resource_attributes.contains_key("pod"));
        assert!(without_list.attributes.is_empty());
    }

    #[test]
    fn structured_metadata_rides_on_the_record_not_the_resource() {
        let mapper = mapper(
            "  service_name: { type: label, name: app }\n  \
             trace_id: { type: structured_metadata, key: trace_id }\n  resource_labels: [app]",
        );

        let record = mapper.map(&entry(
            "line",
            &[("app", "api")],
            &[("trace_id", "4bf92f3577b34da6a3ce929d0e0e4736")],
        ));

        assert_eq!(
            record.trace_id,
            Some("4bf92f3577b34da6a3ce929d0e0e4736".to_string())
        );
        assert_eq!(
            record.attributes.get("trace_id").map(String::as_str),
            Some("4bf92f3577b34da6a3ce929d0e0e4736")
        );
        assert!(!record.resource_attributes.contains_key("trace_id"));
    }

    #[test]
    fn an_extractor_that_matches_nothing_yields_none_rather_than_an_empty_string() {
        let mapper = mapper(
            "  service_name: { type: label, name: app }\n  \
             severity: { type: json_field, path: nested.level }",
        );

        // (case, line, labels)
        let cases = [
            ("a line that is not JSON at all", "not json", vec![]),
            ("JSON without the path", r#"{"other":1}"#, vec![]),
            (
                "the path present but empty",
                r#"{"nested":{"level":""}}"#,
                vec![],
            ),
            (
                "the path present but null",
                r#"{"nested":{"level":null}}"#,
                vec![],
            ),
        ];

        for (case, line, labels) in cases {
            let record = mapper.map(&entry(line, &labels, &[]));

            assert_eq!(record.severity, None, "{case}");
        }
    }

    #[test]
    fn a_trace_id_that_cannot_join_a_span_is_dropped_rather_than_sent() {
        let mapper = mapper(
            "  service_name: { type: label, name: app }\n  \
             trace_id: { type: structured_metadata, key: trace_id }\n  \
             span_id: { type: structured_metadata, key: span_id }",
        );

        // (case, raw trace id, expected)
        let cases = [
            (
                "plain hex",
                "4bf92f3577b34da6a3ce929d0e0e4736",
                Some("4bf92f3577b34da6a3ce929d0e0e4736"),
            ),
            (
                "uppercase is normalized",
                "4BF92F3577B34DA6A3CE929D0E0E4736",
                Some("4bf92f3577b34da6a3ce929d0e0e4736"),
            ),
            (
                "a dashed UUID still maps",
                "4bf92f35-77b3-4da6-a3ce-929d0e0e4736",
                Some("4bf92f3577b34da6a3ce929d0e0e4736"),
            ),
            (
                "a full traceparent is not a trace id",
                "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                None,
            ),
            ("too short", "4bf92f35", None),
            ("not hex", "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", None),
        ];

        for (case, raw, expected) in cases {
            let record = mapper.map(&entry("line", &[("app", "api")], &[("trace_id", raw)]));

            assert_eq!(record.trace_id.as_deref(), expected, "{case}");
        }
    }

    #[test]
    fn hits_counts_what_a_dry_run_reports() {
        let mapper = mapper(
            "  service_name: { type: label, name: app }\n  \
             trace_id: { type: structured_metadata, key: trace_id }",
        );
        let entries = vec![
            entry(
                "a",
                &[("app", "api")],
                &[("trace_id", "4bf92f3577b34da6a3ce929d0e0e4736")],
            ),
            entry("b", &[("app", "api")], &[]),
            entry("c", &[], &[]),
        ];

        let hits = mapper.hits(&entries);

        assert_eq!(hits.total, 3);
        assert_eq!(hits.service_name, 2);
        assert_eq!(hits.trace_id, 1);
    }

    #[test]
    fn severity_text_matches_the_intake_table() {
        for (text, expected) in [
            ("CRITICAL", ("fatal", 21)),
            ("err", ("error", 17)),
            ("Warning", ("warn", 13)),
            ("notice", ("info", 9)),
            ("debug", ("debug", 5)),
            ("trace", ("trace", 1)),
            ("something else", ("info", 9)),
        ] {
            let (name, number) = normalize_severity(text);

            assert_eq!((name.as_str(), number), expected, "severity text {text}");
        }
    }
}
