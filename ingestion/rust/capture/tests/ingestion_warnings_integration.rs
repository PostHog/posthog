//! Integration coverage for the synthetic ingestion warnings emitter.
//!
//! Verifies the leg no other test covers: a real capture server booted with
//! `capture_ingestion_warnings_enabled`, a real Kafka producer built at
//! startup, and a `$$client_ingestion_warning` envelope landing on the
//! warnings topic in response to a validation drop. Every other warnings test
//! either hardcodes the flag false or points the producer at an unroutable
//! address, so producer construction, topic resolution, `build_warnings_kafka_config`,
//! and the delivery path are otherwise unexercised.
//!
//! The Kafka -> ClickHouse leg lives in
//! `nodejs/tests/ingestion/pipelines/clientwarnings/consumer-e2e.test.ts`. The
//! two are pinned to each other by `capture_envelope.fixture.json`: this test
//! asserts capture produces it, that one asserts the consumer accepts it.
//!
//! Requires Docker Kafka (same rig as the other integration tests).

#[path = "common/utils.rs"]
mod utils;
use utils::*;

use anyhow::Result;
use common_types::CapturedEvent;
use serde_json::{json, Value};
use uuid::Uuid;

use capture::v1::analytics::types::Event;
use capture::v1::test_utils::{batch_payload, valid_event};

const TOKEN: &str = "phc_warnings_integration_token";

/// The cross-language envelope pin. See the fixture's own `_comment`.
const ENVELOPE_FIXTURE: &str =
    include_str!("../../common/ingestion_warnings/capture_envelope.fixture.json");

/// An event that fails validation with the `missing_event_name` tag.
fn nameless(distinct_id: &str) -> Event {
    let mut e = valid_event();
    e.uuid = Uuid::new_v4().to_string();
    e.distinct_id = distinct_id.to_string();
    e.event = String::new();
    e
}

#[tokio::test]
async fn v1_validation_drop_emits_warning_envelope_to_kafka() -> Result<()> {
    setup_tracing();
    let events_topic = EphemeralTopic::new().await;
    let warnings_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_v1_topic_with_warnings(&events_topic, &warnings_topic).await;

    // Both events drop under one warning type, which makes
    // `emit_validation_drop_warnings` omit the (then ambiguous) `distinctId`
    // and `eventUuid`, leaving details that are identical on every run and so
    // can be pinned by the fixture.
    let payload = batch_payload(&[nameless("warn-user-0"), nameless("warn-user-1")]);
    let res = server.capture_v1(TOKEN, payload).await;
    assert_eq!(
        res.status(),
        reqwest::StatusCode::OK,
        "an all-dropped batch is still accepted with per-event results"
    );

    let envelope: CapturedEvent = serde_json::from_value(warnings_topic.next_event()?)?;
    assert_eq!(envelope.event, "$$client_ingestion_warning");
    assert_eq!(envelope.token, TOKEN);
    assert_eq!(
        envelope.distinct_id, TOKEN,
        "distinct_id must be the token, never a caller-supplied value"
    );

    let inner: Value = serde_json::from_str(&envelope.data)?;
    let expected: Value = serde_json::from_str(ENVELOPE_FIXTURE)?;
    assert_eq!(inner["event"], expected["event"]);
    assert_eq!(
        inner["properties"], expected["properties"],
        "capture's envelope drifted from the fixture the Node consumer test replays"
    );

    events_topic.assert_empty();
    warnings_topic.assert_empty();
    Ok(())
}

/// The replay path's own leg. Beyond the emitter wiring the tests above cover,
/// this is the only thing that exercises two replay-specific pieces end to end:
/// `v0_endpoint::recording` handing the emitter to the pipeline, and
/// `handle_recording_payload` projecting `$lib`/`$lib_version` out of the
/// snapshot envelope. A regression in either leaves the warning correct in unit
/// tests but absent, or attributed to `unknown`, in production.
#[tokio::test]
async fn replay_validation_abort_emits_warning_envelope_to_kafka() -> Result<()> {
    setup_tracing();
    let token = random_string("phc_replay_warn", 16);
    let events_topic = EphemeralTopic::new().await;
    let warnings_topic = EphemeralTopic::new().await;
    let server = ServerHandle::for_recordings_with_warnings(&events_topic, &warnings_topic).await;

    // Two events so the batch count is distinguishable from a per-event charge,
    // and a `$session_id` that trips the charset rule rather than the length one.
    let properties = json!({
        "$session_id": "not a valid session id",
        "$snapshot_data": [{"type": 1}],
        "$lib": "web",
        "$lib_version": "1.200.0",
    });
    let payload = json!([
        {"event": "$snapshot", "api_key": token, "distinct_id": "u1", "properties": properties},
        {"event": "$snapshot", "api_key": token, "distinct_id": "u1", "properties": properties},
    ]);
    let res = server.capture_recording(payload.to_string(), None).await;
    assert_eq!(
        res.status(),
        reqwest::StatusCode::BAD_REQUEST,
        "an invalid session id rejects the whole replay request"
    );

    let envelope: CapturedEvent = serde_json::from_value(warnings_topic.next_event()?)?;
    assert_eq!(envelope.event, "$$client_ingestion_warning");
    assert_eq!(envelope.token, token);
    assert_eq!(
        envelope.distinct_id, token,
        "distinct_id must be the token, never a caller-supplied value"
    );

    let inner: Value = serde_json::from_str(&envelope.data)?;
    assert_eq!(
        inner["properties"],
        json!({
            "$$client_ingestion_warning_type": "invalid_session_id",
            "$$client_ingestion_warning_source": "capture",
            "$$client_ingestion_warning_details": {
                "count": 2,
                "eventCount": 2,
                "reason": "invalid_charset",
                "sessionIdLength": 22,
                "lib": "web",
                "libVersion": "1.200.0",
                "path": "/s/",
                "pipelineStep": "capture_validation",
            },
        })
    );

    events_topic.assert_empty();
    warnings_topic.assert_empty();
    Ok(())
}

#[tokio::test]
async fn legacy_processing_abort_emits_warning_envelope_to_kafka() -> Result<()> {
    setup_tracing();
    let token = random_string("phc_legacy_warn", 16);
    let events_topic = EphemeralTopic::new().await;
    let historical_topic = EphemeralTopic::new().await;
    let warnings_topic = EphemeralTopic::new().await;
    let server =
        ServerHandle::for_topics_with_warnings(&events_topic, &historical_topic, &warnings_topic)
            .await;

    // The legacy pipeline aborts the whole request on the first invalid
    // event, so the warning charges the full batch count even though
    // processing never reached the second event.
    let properties = json!({"$lib": "posthog-rs", "$lib_version": "1.0.0"});
    let payload = json!({
        "api_key": token,
        "batch": [
            {"event": "no-id-0", "properties": properties},
            {"event": "no-id-1", "properties": properties},
        ],
    });
    let res = server.capture_events(payload.to_string()).await;
    assert_eq!(
        res.status(),
        reqwest::StatusCode::BAD_REQUEST,
        "a legacy batch abort rejects the whole request"
    );

    let envelope: CapturedEvent = serde_json::from_value(warnings_topic.next_event()?)?;
    assert_eq!(envelope.event, "$$client_ingestion_warning");
    assert_eq!(envelope.token, token);
    assert_eq!(
        envelope.distinct_id, token,
        "distinct_id must be the token, never a caller-supplied value"
    );

    let inner: Value = serde_json::from_str(&envelope.data)?;
    assert_eq!(
        inner["properties"],
        json!({
            "$$client_ingestion_warning_type": "missing_distinct_id",
            "$$client_ingestion_warning_source": "capture",
            "$$client_ingestion_warning_details": {
                "count": 2,
                "lib": "posthog-rs",
                "libVersion": "1.0.0",
                "path": "/i/v0/e",
                "pipelineStep": "capture_validation",
            },
        })
    );

    events_topic.assert_empty();
    warnings_topic.assert_empty();
    Ok(())
}
