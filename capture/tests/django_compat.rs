use assert_json_diff::assert_json_matches_no_panic;
use async_trait::async_trait;
use axum::http::StatusCode;
use axum_test_helper::TestClient;
use base64::engine::general_purpose;
use base64::Engine;
use capture::api::{CaptureError, CaptureResponse, CaptureResponseCode};
use capture::event::ProcessedEvent;
use capture::router::router;
use capture::sink::EventSink;
use capture::time::TimeSource;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::{Arc, Mutex};
use time::format_description::well_known::{Iso8601, Rfc3339};
use time::OffsetDateTime;

#[derive(Debug, Deserialize)]
struct RequestDump {
    path: String,
    method: String,
    content_encoding: String,
    content_type: String,
    ip: String,
    now: String,
    body: String,
    output: Vec<Value>,
}

static REQUESTS_DUMP_FILE_NAME: &str = "tests/requests_dump.jsonl";

#[derive(Clone)]
pub struct FixedTime {
    pub time: String,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> String {
        self.time.to_string()
    }
}

#[derive(Clone, Default)]
struct MemorySink {
    events: Arc<Mutex<Vec<ProcessedEvent>>>,
}

impl MemorySink {
    fn len(&self) -> usize {
        self.events.lock().unwrap().len()
    }

    fn events(&self) -> Vec<ProcessedEvent> {
        self.events.lock().unwrap().clone()
    }
}

#[async_trait]
impl EventSink for MemorySink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().unwrap().push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().unwrap().extend_from_slice(&events);
        Ok(())
    }
}

#[tokio::test]
#[ignore]
async fn it_matches_django_capture_behaviour() -> anyhow::Result<()> {
    let file = File::open(REQUESTS_DUMP_FILE_NAME)?;
    let reader = BufReader::new(file);

    let mut mismatches = 0;

    for (line_number, line_contents) in reader.lines().enumerate() {
        let case: RequestDump = serde_json::from_str(&line_contents?)?;
        if !case.path.starts_with("/e/") {
            println!("Skipping {} test case", &case.path);
            continue;
        }

        let raw_body = general_purpose::STANDARD.decode(&case.body)?;
        assert_eq!(
            case.method, "POST",
            "update code to handle method {}",
            case.method
        );

        let sink = MemorySink::default();
        let timesource = FixedTime { time: case.now };
        let app = router(timesource, sink.clone(), false);

        let client = TestClient::new(app);
        let mut req = client.post(&format!("/i/v0{}", case.path)).body(raw_body);
        if !case.content_encoding.is_empty() {
            req = req.header("Content-encoding", case.content_encoding);
        }
        if !case.content_type.is_empty() {
            req = req.header("Content-type", case.content_type);
        }
        if !case.ip.is_empty() {
            req = req.header("X-Forwarded-For", case.ip);
        }
        let res = req.send().await;
        assert_eq!(
            res.status(),
            StatusCode::OK,
            "line {} rejected: {}",
            line_number,
            res.text().await
        );
        assert_eq!(
            Some(CaptureResponse {
                status: CaptureResponseCode::Ok
            }),
            res.json().await
        );
        assert_eq!(
            sink.len(),
            case.output.len(),
            "event count mismatch on line {}",
            line_number
        );

        for (event_number, (message, expected)) in
            sink.events().iter().zip(case.output.iter()).enumerate()
        {
            // Normalizing the expected event to align with known django->rust inconsistencies
            let mut expected = expected.clone();
            if let Some(value) = expected.get_mut("sent_at") {
                // Default ISO format is different between python and rust, both are valid
                // Parse and re-print the value before comparison
                let sent_at =
                    OffsetDateTime::parse(value.as_str().expect("empty"), &Iso8601::DEFAULT)?;
                *value = Value::String(sent_at.format(&Rfc3339)?)
            }

            let match_config = assert_json_diff::Config::new(assert_json_diff::CompareMode::Strict);
            if let Err(e) =
                assert_json_matches_no_panic(&json!(expected), &json!(message), match_config)
            {
                println!(
                    "mismatch at line {}, event {}: {}",
                    line_number, event_number, e
                );
                mismatches += 1;
            }
        }
    }
    assert_eq!(0, mismatches, "some events didn't match");
    Ok(())
}
