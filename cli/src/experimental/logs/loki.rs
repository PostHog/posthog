use std::collections::HashMap;

use anyhow::{bail, Context, Result};
use chrono::{DateTime, Utc};
use reqwest::blocking::{Client, RequestBuilder, Response};
use reqwest::StatusCode;
use serde::Deserialize;

use super::config::Source;

/// Entries kept per page. Loki caps a response at `max_entries_limit_per_query`, 5000 by default.
const PAGE_LIMIT: usize = 1000;

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
                ("start", &nanos(start)?),
                ("end", &nanos(end)?),
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

    /// One page of a shard, oldest first. Returns the entries and the timestamp to resume from,
    /// which is `None` once the shard is exhausted.
    pub fn query_page(
        &self,
        selector: &str,
        start_ns: i64,
        end: DateTime<Utc>,
    ) -> Result<(Vec<Entry>, Option<i64>)> {
        let response = send(
            self.get("/loki/api/v1/query_range").query(&[
                ("query", selector),
                ("start", &start_ns.to_string()),
                ("end", &nanos(end)?),
                ("direction", "forward"),
                // One more than is kept, so a full page is distinguishable from an exhausted shard
                // without inferring it from the count.
                ("limit", &(PAGE_LIMIT + 1).to_string()),
            ]),
            "a query_range page",
        )?;

        let body: QueryResponse = decode(response, "query_range")?;
        let mut entries = entries_from(body)?;

        let has_more = entries.len() > PAGE_LIMIT;
        entries.truncate(PAGE_LIMIT);

        // Resume AT the last kept timestamp, not one nanosecond past it. Loki truncates by entry
        // count, not by timestamp, so entries sharing that instant can still be waiting. Skipping
        // them would lose data silently; the caller suppresses the re-read instead.
        let resume_from = if has_more {
            entries.last().map(|entry| entry.timestamp_ns)
        } else {
            None
        };

        Ok((entries, resume_from))
    }
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
fn nanos(at: DateTime<Utc>) -> Result<String> {
    at.timestamp_nanos_opt()
        .map(|ns| ns.to_string())
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
