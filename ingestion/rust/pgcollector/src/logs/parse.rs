//! Postgres log parsing: `log_line_prefix`-driven prefix regex, multi-line entry
//! assembly, and classification into typed records.

use chrono::{DateTime, NaiveDateTime, Utc};
use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Build a regex for a `log_line_prefix`. Supports the escapes that matter for RDS
/// (`%t %m %n %r %h %u %d %p %Q %a %e %l %x %v %c %s %i %b %P %q %%`).
pub fn prefix_regex(prefix: &str) -> Regex {
    let mut re = String::from("^");
    let mut chars = prefix.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '%' {
            re.push_str(&regex::escape(&c.to_string()));
            continue;
        }
        match chars.next() {
            Some('t') => re.push_str(r"(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? [A-Z]+)"),
            Some('m') => re.push_str(r"(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? [A-Z]+)"),
            Some('n') => re.push_str(r"(?P<epoch>\d+(?:\.\d+)?)"),
            Some('r') => re.push_str(r"(?P<remote>[^:\[]*(?:\[local\])?[^:]*)"),
            Some('h') => re.push_str(r"(?P<host>[^:]*)"),
            Some('u') => re.push_str(r"(?P<user>[^@:\[]*)"),
            Some('d') => re.push_str(r"(?P<db>[^:\[]*)"),
            Some('p') => re.push_str(r"(?P<pid>\d+)"),
            Some('P') => re.push_str(r"(?P<leader>\d*)"),
            Some('Q') => re.push_str(r"(?P<qid>-?\d*)"),
            Some('a') => re.push_str(r"(?P<app>[^:]*)"),
            Some('e') => re.push_str(r"(?P<sqlstate>[0-9A-Z]{5})"),
            Some('l') => re.push_str(r"(?P<line>\d+)"),
            Some('x') => re.push_str(r"(?P<xid>\d+)"),
            Some('v') => re.push_str(r"(?P<vxid>[\d/]*)"),
            Some('c') => re.push_str(r"(?P<session>[0-9a-f.]+)"),
            Some('s') => re.push_str(r"(?P<sess_start>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [A-Z]+)"),
            Some('i') => re.push_str(r"(?P<tag>[^:]*)"),
            Some('b') => re.push_str(r"(?P<btype>[^:]*)"),
            Some('q') => {
                /* rest is session-only; everything after is optional */
                re.push_str("(?:");
            }
            Some('%') => re.push('%'),
            Some(o) => re.push_str(&regex::escape(&o.to_string())),
            None => {}
        }
    }
    if prefix.contains("%q") {
        re.push_str(")?");
    }
    re.push_str(r"\s*(?P<level>LOG|ERROR|FATAL|PANIC|WARNING|NOTICE|INFO|DEBUG[1-5]?|DETAIL|HINT|STATEMENT|CONTEXT|QUERY|LOCATION):\s{0,2}(?P<msg>.*)$");
    Regex::new(&re).expect("prefix regex")
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Entry {
    pub ts: Option<DateTime<Utc>>,
    pub pid: Option<i64>,
    pub user: Option<String>,
    pub db: Option<String>,
    pub remote: Option<String>,
    pub app: Option<String>,
    pub query_id: Option<i64>,
    pub sqlstate: Option<String>,
    pub level: String,
    pub message: String,
    pub detail: Option<String>,
    pub hint: Option<String>,
    pub statement: Option<String>,
    pub context: Option<String>,
    pub query: Option<String>,
    /// Which field the last line went to, for tab-continuations.
    #[serde(skip)]
    last: Last,
}

#[derive(Debug, Clone, Copy, Default, PartialEq)]
enum Last {
    #[default]
    Message,
    Detail,
    Hint,
    Statement,
    Context,
    Query,
}

impl Entry {
    fn append(&mut self, text: &str) {
        let f = match self.last {
            Last::Message => &mut self.message,
            Last::Detail => self.detail.get_or_insert_with(String::new),
            Last::Hint => self.hint.get_or_insert_with(String::new),
            Last::Statement => self.statement.get_or_insert_with(String::new),
            Last::Context => self.context.get_or_insert_with(String::new),
            Last::Query => self.query.get_or_insert_with(String::new),
        };
        f.push('\n');
        f.push_str(text);
    }
}

/// Turns lines into complete entries. Keep one per log stream; serialise `pending`
/// into collector state between ticks.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Assembler {
    pub pending: Option<Entry>,
}

fn parse_ts(s: &str) -> Option<DateTime<Utc>> {
    // "2026-08-27 18:22:49 UTC" or with .123 ms; RDS always logs UTC.
    let s = s.trim_end_matches(" UTC").trim_end_matches(" GMT");
    NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S%.f")
        .or_else(|_| NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S"))
        .ok()
        .map(|n| n.and_utc())
}

impl Assembler {
    pub fn push(&mut self, re: &Regex, line: &str) -> Option<Entry> {
        let line = line.strip_suffix('\r').unwrap_or(line);
        if line.is_empty() {
            return None;
        }
        if line.starts_with('\t') || line.starts_with("        ") {
            if let Some(p) = &mut self.pending {
                p.append(line.trim_start_matches('\t'));
            }
            return None;
        }
        let Some(m) = re.captures(line) else {
            // Unparseable, treat as continuation (RDS sometimes wraps).
            if let Some(p) = &mut self.pending {
                p.append(line);
            }
            return None;
        };
        let level = m.name("level").map(|x| x.as_str()).unwrap_or("");
        let msg = m.name("msg").map(|x| x.as_str()).unwrap_or("").to_string();
        let pid = m.name("pid").and_then(|x| x.as_str().parse().ok());
        let secondary = matches!(
            level,
            "DETAIL" | "HINT" | "STATEMENT" | "CONTEXT" | "QUERY" | "LOCATION"
        );
        if secondary {
            if let Some(p) = &mut self.pending {
                if p.pid == pid || pid.is_none() {
                    match level {
                        "DETAIL" => {
                            p.detail = Some(msg);
                            p.last = Last::Detail;
                        }
                        "HINT" => {
                            p.hint = Some(msg);
                            p.last = Last::Hint;
                        }
                        "STATEMENT" => {
                            p.statement = Some(msg);
                            p.last = Last::Statement;
                        }
                        "CONTEXT" => {
                            p.context = Some(msg);
                            p.last = Last::Context;
                        }
                        "QUERY" => {
                            p.query = Some(msg);
                            p.last = Last::Query;
                        }
                        _ => {}
                    }
                    return None;
                }
            }
            return None; // orphan secondary line
        }
        let opt = |n: &str| {
            m.name(n)
                .map(|x| x.as_str().trim().to_string())
                .filter(|s| !s.is_empty())
        };
        let e = Entry {
            ts: m.name("ts").and_then(|x| parse_ts(x.as_str())).or_else(|| {
                m.name("epoch")
                    .and_then(|x| x.as_str().parse::<f64>().ok())
                    .and_then(|f| DateTime::from_timestamp((f) as i64, ((f.fract()) * 1e9) as u32))
            }),
            pid,
            user: opt("user"),
            db: opt("db"),
            remote: opt("remote").or_else(|| opt("host")),
            app: opt("app"),
            query_id: m
                .name("qid")
                .and_then(|x| x.as_str().parse().ok())
                .filter(|q| *q != 0),
            sqlstate: opt("sqlstate"),
            level: level.to_string(),
            message: msg,
            ..Default::default()
        };
        self.pending.replace(e)
    }

    pub fn flush(&mut self) -> Option<Entry> {
        self.pending.take()
    }
}

// ---------- classification ----------

#[derive(Debug, Clone, PartialEq)]
pub enum Record {
    Duration {
        duration_ms: f64,
        kind: String,
        query: Option<String>,
    },
    Plan {
        duration_ms: f64,
        query: Option<String>,
        plan: serde_json::Value,
    },
    Autovacuum(BTreeMap<String, serde_json::Value>),
    Checkpoint(BTreeMap<String, serde_json::Value>),
    LockWait {
        waiting_pid: i64,
        lock_type: String,
        target: String,
        wait_ms: f64,
        acquired: bool,
    },
    Deadlock,
    TempFile {
        size_bytes: i64,
        path: String,
    },
    Cancel {
        reason: String,
    },
    Connection {
        what: String,
    },
    Error,
    Other,
}

static DURATION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?s)^duration: ([\d.]+) ms(?:  (statement|execute [^:]*|bind [^:]*|parse [^:]*|plan): ?(.*))?$").unwrap()
});
static AUTOVAC: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?s)^automatic (aggressive )?(vacuum|analyze) of table "([^"]+)"(.*)$"#).unwrap()
});
static CHECKPOINT: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^(checkpoint|restartpoint) complete: wrote (\d+) buffers \(([\d.]+)%\); (\d+) WAL file\(s\) added, (\d+) removed, (\d+) recycled; write=([\d.]+) s, sync=([\d.]+) s, total=([\d.]+) s; sync files=(\d+), longest=([\d.]+) s, average=([\d.]+) s; distance=(\d+) kB, estimate=(\d+) kB").unwrap()
});
static LOCKWAIT: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^process (\d+) (still waiting for|acquired) (\w+) on (.+?) after ([\d.]+) ms$")
        .unwrap()
});
static TEMPFILE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"^temporary file: path "([^"]+)", size (\d+)"#).unwrap());
static CANCEL: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^canceling (?:statement|autovacuum task) due to (.+)$").unwrap());
static CONN: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"^(connection received|connection authorized|connection authenticated|disconnection)",
    )
    .unwrap()
});

fn num(re: &Regex, s: &str) -> Option<Vec<f64>> {
    re.captures(s).map(|c| {
        c.iter()
            .skip(1)
            .filter_map(|m| m.and_then(|m| m.as_str().parse().ok()))
            .collect()
    })
}

pub fn classify(e: &Entry) -> Record {
    let m = e.message.as_str();
    if let Some(c) = DURATION.captures(m) {
        let d: f64 = c[1].parse().unwrap_or(0.0);
        let kind = c
            .get(2)
            .map(|k| k.as_str().split(' ').next().unwrap_or("").to_string())
            .unwrap_or_default();
        let text = c.get(3).map(|t| t.as_str().to_string());
        if kind == "plan" {
            let plan = text
                .as_deref()
                .and_then(|t| serde_json::from_str::<serde_json::Value>(t.trim()).ok())
                .unwrap_or(serde_json::Value::Null);
            let q = plan
                .get("Query Text")
                .and_then(|v| v.as_str())
                .map(str::to_string);
            return Record::Plan {
                duration_ms: d,
                query: q,
                plan,
            };
        }
        return Record::Duration {
            duration_ms: d,
            kind,
            query: text,
        };
    }
    if let Some(c) = AUTOVAC.captures(m) {
        static PAGES: Lazy<Regex> =
            Lazy::new(|| Regex::new(r"pages: (\d+) removed, (\d+) remain").unwrap());
        static TUPLES: Lazy<Regex> = Lazy::new(|| {
            Regex::new(r"tuples: (\d+) removed, (\d+) remain, (\d+) are dead but not yet removable")
                .unwrap()
        });
        static SCANS: Lazy<Regex> = Lazy::new(|| Regex::new(r"index scans: (\d+)").unwrap());
        static RATES: Lazy<Regex> = Lazy::new(|| {
            Regex::new(r"avg read rate: ([\d.]+) MB/s, avg write rate: ([\d.]+) MB/s").unwrap()
        });
        static BUF: Lazy<Regex> = Lazy::new(|| {
            Regex::new(r"buffer usage: (\d+) hits, (\d+) (?:misses|reads), (\d+) dirtied").unwrap()
        });
        static WAL: Lazy<Regex> = Lazy::new(|| {
            Regex::new(r"WAL usage: (\d+) records, (\d+) full page images, (\d+) bytes").unwrap()
        });
        static SYS: Lazy<Regex> = Lazy::new(|| {
            Regex::new(
                r"system usage: CPU: user: ([\d.]+) s, system: ([\d.]+) s, elapsed: ([\d.]+) s",
            )
            .unwrap()
        });
        static FROZEN: Lazy<Regex> = Lazy::new(|| {
            Regex::new(
                r"frozen: (\d+) pages from table \(([\d.]+)% of total\) had (\d+) tuples frozen",
            )
            .unwrap()
        });
        let rest = &c[4];
        let mut r = BTreeMap::new();
        let j = |v: f64| serde_json::json!(v);
        r.insert("kind".into(), serde_json::json!(&c[2]));
        r.insert("aggressive".into(), serde_json::json!(c.get(1).is_some()));
        r.insert("relation".into(), serde_json::json!(&c[3]));
        if let Some(v) = num(&SCANS, rest) {
            r.insert("index_scans".into(), j(v[0]));
        }
        if let Some(v) = num(&PAGES, rest) {
            r.insert("pages_removed".into(), j(v[0]));
            r.insert("pages_remain".into(), j(v[1]));
        }
        if let Some(v) = num(&TUPLES, rest) {
            r.insert("tuples_removed".into(), j(v[0]));
            r.insert("tuples_remain".into(), j(v[1]));
            r.insert("tuples_dead_not_removable".into(), j(v[2]));
        }
        if let Some(v) = num(&FROZEN, rest) {
            r.insert("pages_frozen".into(), j(v[0]));
            r.insert("tuples_frozen".into(), j(v[2]));
        }
        if let Some(v) = num(&RATES, rest) {
            r.insert("read_mb_s".into(), j(v[0]));
            r.insert("write_mb_s".into(), j(v[1]));
        }
        if let Some(v) = num(&BUF, rest) {
            r.insert("buffer_hits".into(), j(v[0]));
            r.insert("buffer_misses".into(), j(v[1]));
            r.insert("buffer_dirtied".into(), j(v[2]));
        }
        if let Some(v) = num(&WAL, rest) {
            r.insert("wal_records".into(), j(v[0]));
            r.insert("wal_fpi".into(), j(v[1]));
            r.insert("wal_bytes".into(), j(v[2]));
        }
        if let Some(v) = num(&SYS, rest) {
            r.insert("cpu_user_s".into(), j(v[0]));
            r.insert("cpu_system_s".into(), j(v[1]));
            r.insert("elapsed_s".into(), j(v[2]));
        }
        return Record::Autovacuum(r);
    }
    if let Some(v) = num(&CHECKPOINT, m) {
        let names = [
            "buffers_written",
            "buffers_pct",
            "wal_added",
            "wal_removed",
            "wal_recycled",
            "write_s",
            "sync_s",
            "total_s",
            "sync_files",
            "sync_longest_s",
            "sync_average_s",
            "distance_kb",
            "estimate_kb",
        ];
        let mut r: BTreeMap<String, serde_json::Value> = names
            .iter()
            .zip(v)
            .map(|(n, x)| (n.to_string(), serde_json::json!(x)))
            .collect();
        r.insert(
            "kind".into(),
            serde_json::json!(if m.starts_with("restartpoint") {
                "restartpoint"
            } else {
                "checkpoint"
            }),
        );
        return Record::Checkpoint(r);
    }
    if let Some(c) = LOCKWAIT.captures(m) {
        return Record::LockWait {
            waiting_pid: c[1].parse().unwrap_or(0),
            acquired: &c[2] == "acquired",
            lock_type: c[3].to_string(),
            target: c[4].to_string(),
            wait_ms: c[5].parse().unwrap_or(0.0),
        };
    }
    if m.starts_with("deadlock detected") {
        return Record::Deadlock;
    }
    if let Some(c) = TEMPFILE.captures(m) {
        return Record::TempFile {
            path: c[1].to_string(),
            size_bytes: c[2].parse().unwrap_or(0),
        };
    }
    if let Some(c) = CANCEL.captures(m) {
        return Record::Cancel {
            reason: c[1].to_string(),
        };
    }
    if let Some(c) = CONN.captures(m) {
        return Record::Connection {
            what: c[1].to_string(),
        };
    }
    if matches!(e.level.as_str(), "ERROR" | "FATAL" | "PANIC") {
        return Record::Error;
    }
    Record::Other
}

#[cfg(test)]
mod tests {
    use super::*;
    const PREFIX: &str = "%t:%r:%u@%d:[%p]:%Q:";

    #[test]
    fn parses_rds_style_lines_with_continuations() {
        let re = prefix_regex(PREFIX);
        let mut a = Assembler::default();
        let lines = [
            "2026-08-27 18:22:49 UTC:[local]:postgres@app:[132]:7519653867268795551:LOG:  duration: 0.006 ms  plan:",
            "\t{",
            "\t  \"Query Text\": \"select 1\",",
            "\t  \"Plan\": { \"Node Type\": \"Result\" }",
            "\t}",
            "2026-08-27 18:22:49 UTC:[local]:postgres@app:[132]:7519653867268795551:LOG:  duration: 0.598 ms  statement: select count(*) from t where id < 50",
            "2026-08-27 18:22:50 UTC:10.1.2.3(5000):app@app:[140]:0:ERROR:  canceling statement due to statement timeout",
            "2026-08-27 18:22:50 UTC:10.1.2.3(5000):app@app:[140]:0:STATEMENT:  update t set v = 'x'",
            "2026-08-27 18:22:51 UTC::@:[7]::LOG:  checkpoint complete: wrote 12 buffers (0.1%); 0 WAL file(s) added, 0 removed, 1 recycled; write=1.001 s, sync=0.002 s, total=1.010 s; sync files=9, longest=0.001 s, average=0.001 s; distance=100 kB, estimate=100 kB",
        ];
        let mut out = Vec::new();
        for l in lines {
            if let Some(e) = a.push(&re, l) {
                out.push(e);
            }
        }
        if let Some(e) = a.flush() {
            out.push(e);
        }
        assert_eq!(out.len(), 4);
        match classify(&out[0]) {
            Record::Plan { query, plan, .. } => {
                assert_eq!(query.as_deref(), Some("select 1"));
                assert_eq!(plan["Plan"]["Node Type"], "Result");
            }
            r => panic!("{r:?}"),
        }
        assert_eq!(out[0].query_id, Some(7519653867268795551));
        match classify(&out[1]) {
            Record::Duration {
                duration_ms,
                kind,
                query,
            } => {
                assert_eq!(duration_ms, 0.598);
                assert_eq!(kind, "statement");
                assert!(query.unwrap().starts_with("select count"));
            }
            r => panic!("{r:?}"),
        }
        assert_eq!(out[2].level, "ERROR");
        assert_eq!(out[2].statement.as_deref(), Some("update t set v = 'x'"));
        assert_eq!(out[2].remote.as_deref(), Some("10.1.2.3(5000)"));
        assert!(matches!(classify(&out[2]), Record::Cancel { .. }));
        match classify(&out[3]) {
            Record::Checkpoint(r) => assert_eq!(r["buffers_written"], 12.0),
            r => panic!("{r:?}"),
        }
    }

    #[test]
    fn default_rds_prefix_and_autovacuum() {
        let re = prefix_regex("%t:%r:%u@%d:[%p]:");
        let mut a = Assembler::default();
        let l1 = "2026-08-27 18:22:49 UTC::@:[55]:LOG:  automatic vacuum of table \"app.public.t\": index scans: 1";
        let l2 = "\tpages: 0 removed, 84 remain, 84 scanned (100.00% of total)";
        let l3 = "\ttuples: 15000 removed, 5000 remain, 0 are dead but not yet removable";
        let l4 = "\tbuffer usage: 200 hits, 3 misses, 90 dirtied";
        let l5 = "\tsystem usage: CPU: user: 0.01 s, system: 0.00 s, elapsed: 0.05 s";
        for l in [l1, l2, l3, l4, l5] {
            a.push(&re, l);
        }
        let e = a.flush().unwrap();
        match classify(&e) {
            Record::Autovacuum(r) => {
                assert_eq!(r["relation"], "app.public.t");
                assert_eq!(r["tuples_removed"], 15000.0);
                assert_eq!(r["elapsed_s"], 0.05);
            }
            r => panic!("{r:?}"),
        }
    }
}
