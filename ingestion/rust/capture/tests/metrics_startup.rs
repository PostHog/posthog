//! Metrics emitted during `build_components` must reach `/metrics`. Whether
//! they do depends on the global recorder being installed first, which only the
//! real startup path exercises: a unit test's local recorder always exists.
//!
//! One test per binary, since the recorder installs once per process.

use std::time::Duration;

#[path = "common/utils.rs"]
mod test_utils;
use test_utils::{setup_tracing, ServerHandle, DEFAULT_CONFIG};

#[tokio::test]
async fn startup_gauge_reaches_the_scrape_endpoint() {
    setup_tracing();

    let mut config = DEFAULT_CONFIG.clone();
    config.export_prometheus = true;
    // Warnings enabled but no hosts, so the emitter reports `0` during startup.
    config.capture_ingestion_warnings_enabled = true;
    config.capture_ingestion_warnings_kafka_hosts = String::new();

    let server = ServerHandle::for_config(config).await;

    let body = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .expect("http client")
        .get(format!("http://{}/metrics", server.addr))
        .send()
        .await
        .expect("scrape /metrics")
        .text()
        .await
        .expect("read scrape body");

    let line = body
        .lines()
        .find(|line| line.starts_with("ingestion_warnings_emitter_enabled{"))
        .unwrap_or_else(|| panic!("gauge missing, startup metrics are being dropped"));

    assert!(
        line.contains(r#"reason="hosts_unset""#),
        "gauge must name the misconfiguration: {line}"
    );
    assert!(line.ends_with(" 0"), "emitter is down, expected 0: {line}");
    // The recorder's global labels only land if it was installed before the
    // emission, so checking them also pins the ordering.
    assert!(
        line.contains(r#"capture_mode="events""#) && line.contains(r#"role="capture-testing""#),
        "gauge must carry the recorder's global labels: {line}"
    );
}
