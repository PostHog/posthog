use std::collections::HashMap;

use anyhow::{bail, Context, Result};
use chrono::{DateTime, Utc};
use reqwest::blocking::{Client, RequestBuilder, Response};
use reqwest::StatusCode;
use serde::Deserialize;

use super::config::Source;

/// Entries kept per page, well under Loki's per-request cap (see `INSTANT_LIMIT`).
const PAGE_LIMIT: usize = 1000;

/// The most entries one request may ask for under Loki's default `max_entries_limit_per_query`.
/// Reading one instant needs the largest page Loki allows, because it cannot page within an instant.
pub const INSTANT_LIMIT: usize = 5000;

pub struct LokiClient {
    http: Client,
    base_url: String,
    tenant: Option<String>,
    auth: LokiAuth,
}

pub enum LokiAuth {
    None,
    Basic { username: String, password: String },
    Bearer { token: String },
}

impl LokiAuth {
    pub fn from_env() -> Self {
        Self::resolve(
            std::env::var("LOKI_BEARER_TOKEN").ok(),
            std::env::var("LOKI_USERNAME").ok(),
            std::env::var("LOKI_PASSWORD").ok(),
        )
    }

    /// Grafana Cloud uses basic auth with the numeric instance id as the username, while a
    /// self-hosted gateway usually sits behind a bearer token. A bearer token wins when both are
    /// set, rather than silently sending the wrong one.
    fn resolve(bearer: Option<String>, username: Option<String>, password: Option<String>) -> Self {
        if let Some(token) = bearer.filter(|t| !t.is_empty()) {
            return LokiAuth::Bearer { token };
        }
        match (username.filter(|u| !u.is_empty()), password) {
            (Some(username), Some(password)) => LokiAuth::Basic { username, password },
            _ => LokiAuth::None,
        }
    }
}

/// One log line as Loki returns it.
#[derive(Debug, Clone)]
pub struct Entry {
    pub timestamp_ns: i64,
    pub line: String,
    pub structured_metadata: HashMap<String, String>,
    pub labels: HashMap<String, String>,
}

#[derive(Debug, Deserialize)]
struct QueryResponse {
    data: QueryData,
}

#[derive(Debug, Deserialize)]
struct QueryData {
    #[serde(default)]
    result: Vec<StreamResult>,
}

#[derive(Debug, Deserialize)]
struct StreamResult {
    stream: HashMap<String, String>,
    #[serde(default)]
    values: Vec<StreamValue>,
}

/// `[timestamp_ns, line]` before Loki 3.0, `[timestamp_ns, line, {metadata}]` after it.
#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum StreamValue {
    WithMetadata(String, String, HashMap<String, String>),
    Bare(String, String),
}

#[derive(Debug, Deserialize)]
struct VolumeResponse {
    data: VolumeData,
}

#[derive(Debug, Deserialize)]
struct VolumeData {
    #[serde(default)]
    result: Vec<VolumeResult>,
}

#[derive(Debug, Deserialize)]
struct VolumeResult {
    #[serde(default)]
    values: Vec<(f64, String)>,
}

impl LokiClient {
    pub fn new(source: &Source, auth: LokiAuth, http: Client) -> Self {
        Self {
            http,
            base_url: source.url.as_str().trim_end_matches('/').to_string(),
            tenant: source.tenant.clone(),
            auth,
        }
    }

    fn get(&self, path: &str) -> RequestBuilder {
        let mut request = self.http.get(format!("{}{path}", self.base_url));
        if let Some(tenant) = &self.tenant {
            request = request.header("X-Scope-OrgID", tenant);
        }
        match &self.auth {
            LokiAuth::None => request,
            LokiAuth::Basic { username, password } => request.basic_auth(username, Some(password)),
            LokiAuth::Bearer { token } => request.bearer_auth(token),
        }
    }

    /// Bytes stored per selector over a window, used to size a run before it moves any data.
    pub fn volume_bytes(
        &self,
        selector: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> Result<u64> {
        let response = send(
            self.get("/loki/api/v1/index/volume_range").query(&[
                ("query", selector),
                ("start", &nanos(start)?.to_string()),
                ("end", &nanos(end)?.to_string()),
                ("step", "24h"),
            ]),
            "a volume lookup",
        )?;

        let body: VolumeResponse = decode(response, "index/volume_range")?;
        let total = body
            .data
            .result
            .iter()
            .flat_map(|series| series.values.iter())
            .filter_map(|(_, value)| value.parse::<f64>().ok())
            .sum::<f64>();
        Ok(total as u64)
    }

    /// One page of a shard, oldest first.
    pub fn query_page(&self, selector: &str, start_ns: i64, end: DateTime<Utc>) -> Result<Page> {
        // One more than is kept, so a full page is distinguishable from an exhausted shard without
        // inferring it from the count.
        let entries = self.query_range(selector, start_ns, nanos(end)?, PAGE_LIMIT + 1)?;
        Ok(split_page(entries, PAGE_LIMIT))
    }

    pub fn sample(
        &self,
        selector: &str,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        limit: usize,
    ) -> Result<Vec<Entry>> {
        self.query_range(selector, nanos(start)?, nanos(end)?, limit)
    }

    /// Every entry at exactly `at_ns`, or `None` when the instant holds `INSTANT_LIMIT` entries or
    /// more, which no single request can read.
    pub fn query_instant(&self, selector: &str, at_ns: i64) -> Result<Option<Vec<Entry>>> {
        // `end` is exclusive, so this range holds one nanosecond.
        let entries = self.query_range(selector, at_ns, at_ns + 1, INSTANT_LIMIT)?;
        Ok((entries.len() < INSTANT_LIMIT).then_some(entries))
    }

    fn query_range(
        &self,
        selector: &str,
        start_ns: i64,
        end_ns: i64,
        limit: usize,
    ) -> Result<Vec<Entry>> {
        let response = send(
            self.get("/loki/api/v1/query_range").query(&[
                ("query", selector),
                ("start", &start_ns.to_string()),
                ("end", &end_ns.to_string()),
                ("direction", "forward"),
                ("limit", &limit.to_string()),
            ]),
            "a query_range page",
        )?;

        let body: QueryResponse = decode(response, "query_range")?;
        entries_from(body)
    }
}

#[derive(Debug)]
pub enum Page {
    Last(Vec<Entry>),
    More {
        entries: Vec<Entry>,
        resume_at: i64,
    },
    /// A full page that holds one instant only. Loki answers every query starting at that instant
    /// with the same page, so paging cannot get past it.
    Crowded(i64),
}

/// `entries` is one request of up to `limit + 1` entries, oldest first.
///
/// Loki truncates a response by entry count, so the instant of the entry past the limit can be cut
/// short. Every instant before it is complete, so the page keeps only those and the next page starts
/// at that instant. Nothing is sent twice and nothing needs to be deduplicated.
fn split_page(entries: Vec<Entry>, limit: usize) -> Page {
    let Some(overflow) = entries.get(limit) else {
        return Page::Last(entries);
    };
    let resume_at = overflow.timestamp_ns;
    let complete = entries.partition_point(|entry| entry.timestamp_ns < resume_at);
    if complete == 0 {
        return Page::Crowded(resume_at);
    }
    let mut entries = entries;
    entries.truncate(complete);
    Page::More { entries, resume_at }
}

/// Flattens Loki's per-stream blocks into one timestamp-ordered run.
fn entries_from(body: QueryResponse) -> Result<Vec<Entry>> {
    let mut entries = Vec::new();
    for stream in body.data.result {
        for value in stream.values {
            let (raw_ts, line, metadata) = match value {
                StreamValue::WithMetadata(ts, line, metadata) => (ts, line, metadata),
                StreamValue::Bare(ts, line) => (ts, line, HashMap::new()),
            };
            let timestamp_ns = raw_ts
                .parse::<i64>()
                .with_context(|| format!("Loki returned an unparseable timestamp: {raw_ts}"))?;
            entries.push(Entry {
                timestamp_ns,
                line,
                structured_metadata: metadata,
                labels: stream.stream.clone(),
            });
        }
    }

    // Loki returns one block per stream, so a page arrives interleaved across streams.
    entries.sort_by_key(|entry| entry.timestamp_ns);
    Ok(entries)
}

/// The config rejects a range outside chrono's nanosecond span, so `None` here means the caller
/// bypassed validation rather than that the user asked for it.
fn nanos(at: DateTime<Utc>) -> Result<i64> {
    at.timestamp_nanos_opt()
        .with_context(|| format!("{at} is outside the range Loki nanosecond epochs can express"))
}

/// reqwest exposes no typed variant for a trust failure, so this matches the rustls message.
fn tls_trust_hint(error: &(dyn std::error::Error + 'static)) -> &'static str {
    let mut cause = Some(error);
    while let Some(current) = cause {
        if current.to_string().contains("invalid peer certificate") {
            return " The certificate is signed by an authority this machine does not trust. \
                    Install that authority's root certificate on this machine, or set SSL_CERT_FILE \
                    to a PEM file holding it.";
        }
        cause = current.source();
    }
    ""
}

fn send(request: RequestBuilder, what: &str) -> Result<Response> {
    request.send().map_err(|error| {
        let hint = tls_trust_hint(&error);
        anyhow::Error::new(error).context(format!("failed to reach Loki for {what}.{hint}"))
    })
}

fn decode<T: serde::de::DeserializeOwned>(response: Response, endpoint: &str) -> Result<T> {
    let status = response.status();
    if !status.is_success() {
        let body = response.text().unwrap_or_default();
        let hint = match status {
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                " Check LOKI_USERNAME/LOKI_PASSWORD or LOKI_BEARER_TOKEN."
            }
            StatusCode::BAD_REQUEST => {
                " Check the selector and that the shard is inside Loki's max_query_length."
            }
            StatusCode::TOO_MANY_REQUESTS => " Loki is rate limiting this query; retry later.",
            _ => "",
        };
        bail!("Loki {endpoint} returned {status}.{hint} Body: {body}");
    }
    response
        .json::<T>()
        .with_context(|| format!("failed to decode the Loki {endpoint} response"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(timestamps: &[i64]) -> Vec<Entry> {
        timestamps
            .iter()
            .enumerate()
            .map(|(i, &timestamp_ns)| Entry {
                timestamp_ns,
                line: format!("line {i}"),
                structured_metadata: HashMap::new(),
                labels: HashMap::new(),
            })
            .collect()
    }

    fn timestamps(entries: &[Entry]) -> Vec<i64> {
        entries.iter().map(|entry| entry.timestamp_ns).collect()
    }

    #[test]
    fn a_page_keeps_only_complete_instants_and_resumes_at_the_cut_one() {
        // Loki cut the response inside instant 30, so its entries wait for the next page, which
        // starts at 30 and returns all of them. Sending them now would send them twice.
        match split_page(at(&[10, 20, 30, 30]), 3) {
            Page::More { entries, resume_at } => {
                assert_eq!(timestamps(&entries), [10, 20]);
                assert_eq!(resume_at, 30);
            }
            page => panic!("expected More, got {page:?}"),
        }
    }

    #[test]
    fn a_full_page_of_one_instant_is_crowded_rather_than_empty() {
        // Keeping no entries and resuming at the same instant would ask Loki for the same page
        // forever.
        assert!(matches!(
            split_page(at(&[30, 30, 30, 30]), 3),
            Page::Crowded(30)
        ));
    }

    #[test]
    fn a_page_under_the_limit_is_the_last_and_keeps_everything() {
        match split_page(at(&[10, 20, 20]), 3) {
            Page::Last(entries) => assert_eq!(timestamps(&entries), [10, 20, 20]),
            page => panic!("expected Last, got {page:?}"),
        }
    }

    #[derive(Debug)]
    struct Layer(&'static str, Option<Box<Layer>>);

    impl std::fmt::Display for Layer {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.write_str(self.0)
        }
    }

    impl std::error::Error for Layer {
        fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
            self.1
                .as_deref()
                .map(|inner| inner as &(dyn std::error::Error + 'static))
        }
    }

    #[test]
    fn tls_trust_hint_reads_the_whole_chain() {
        // The trust failure is never the outermost error, which is what this pins.
        let trust_failure = Layer(
            "error sending request for url (https://loki.example.com)",
            Some(Box::new(Layer(
                "invalid peer certificate: UnknownIssuer",
                None,
            ))),
        );
        assert!(tls_trust_hint(&trust_failure).contains("SSL_CERT_FILE"));

        let unreachable = Layer("connection refused", None);
        assert!(tls_trust_hint(&unreachable).is_empty());
    }

    fn parse(json: &str) -> Vec<Entry> {
        let body: QueryResponse = serde_json::from_str(json).expect("decodes");
        entries_from(body).expect("entries")
    }

    #[test]
    fn decodes_entries_with_and_without_structured_metadata() {
        // Loki before 3.0 returns two elements per value, 3.0 and later return three.
        let entries = parse(
            r#"{"data":{"result":[
                {"stream":{"app":"api"},"values":[
                    ["1700000000000000001","old shape"]
                ]},
                {"stream":{"app":"web"},"values":[
                    ["1700000000000000002","new shape",{"trace_id":"abc"}]
                ]}
            ]}}"#,
        );

        assert_eq!(entries.len(), 2);
        assert!(entries[0].structured_metadata.is_empty());
        assert_eq!(
            entries[1]
                .structured_metadata
                .get("trace_id")
                .map(String::as_str),
            Some("abc")
        );
        assert_eq!(
            entries[1].labels.get("app").map(String::as_str),
            Some("web")
        );
    }

    #[test]
    fn merges_interleaved_streams_into_timestamp_order() {
        // Loki returns one block per stream, so a page arrives out of order across streams.
        let entries = parse(
            r#"{"data":{"result":[
                {"stream":{"app":"a"},"values":[["300","third"],["100","first"]]},
                {"stream":{"app":"b"},"values":[["200","second"]]}
            ]}}"#,
        );

        let lines: Vec<&str> = entries.iter().map(|e| e.line.as_str()).collect();
        assert_eq!(lines, ["first", "second", "third"]);
    }

    #[test]
    fn an_empty_result_decodes_rather_than_erroring() {
        assert!(parse(r#"{"data":{"result":[]}}"#).is_empty());
        assert!(parse(r#"{"data":{}}"#).is_empty());
    }

    #[test]
    fn auth_resolution_picks_one_scheme() {
        let some = |s: &str| Some(s.to_string());

        // (case, bearer, username, password, expected scheme)
        let cases = [
            (
                "a bearer token wins over basic",
                some("tok"),
                some("123"),
                some("pw"),
                "bearer",
            ),
            (
                "basic when no bearer token",
                None,
                some("123"),
                some("pw"),
                "basic",
            ),
            (
                "an empty bearer falls through",
                some(""),
                some("123"),
                some("pw"),
                "basic",
            ),
            (
                "a username with no password is not basic",
                None,
                some("123"),
                None,
                "none",
            ),
            ("nothing set", None, None, None, "none"),
        ];

        for (case, bearer, username, password, expected) in cases {
            let resolved = match LokiAuth::resolve(bearer, username, password) {
                LokiAuth::Bearer { .. } => "bearer",
                LokiAuth::Basic { .. } => "basic",
                LokiAuth::None => "none",
            };

            assert_eq!(resolved, expected, "{case}");
        }
    }
}
