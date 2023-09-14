use assert_json_diff::assert_json_eq;
use async_trait::async_trait;
use axum::http::StatusCode;
use axum_test_helper::TestClient;
use base64::engine::general_purpose;
use base64::Engine;
use capture::api::{CaptureResponse, CaptureResponseCode};
use capture::event::ProcessedEvent;
use capture::router::router;
use capture::sink::EventSink;
use capture::time::TimeSource;
use serde::Deserialize;
use serde_json::{json, Value};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::sync::{Arc, Mutex};

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
    async fn send(&self, event: ProcessedEvent) -> anyhow::Result<()> {
        self.events.lock().unwrap().push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> anyhow::Result<()> {
        self.events.lock().unwrap().extend_from_slice(&events);
        Ok(())
    }
}

#[tokio::test]
#[ignore]
async fn it_matches_django_capture_behaviour() -> anyhow::Result<()> {
    let file = File::open(REQUESTS_DUMP_FILE_NAME)?;
    let reader = BufReader::new(file);

    for line in reader.lines() {
        let case: RequestDump = serde_json::from_str(&line?)?;
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
        let app = router(timesource, sink.clone());

        let client = TestClient::new(app);
        let mut req = client.post(&case.path).body(raw_body);
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
        assert_eq!(res.status(), StatusCode::OK, "{}", res.text().await);
        assert_eq!(
            Some(CaptureResponse {
                status: CaptureResponseCode::Ok
            }),
            res.json().await
        );
        assert_eq!(sink.len(), case.output.len());
        assert_json_eq!(json!(case.output), json!(sink.events()))
    }
    Ok(())
}
