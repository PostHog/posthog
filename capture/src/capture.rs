use std::collections::HashSet;
use std::ops::Deref;
use std::sync::Arc;

use bytes::Bytes;

use axum::Json;
// TODO: stream this instead
use axum::extract::{Query, State};
use axum::http::{HeaderMap, Method};
use axum_client_ip::InsecureClientIp;
use base64::Engine;
use metrics::counter;

use time::OffsetDateTime;
use tracing::instrument;

use crate::event::{Compression, ProcessingContext};
use crate::limiters::billing::QuotaResource;
use crate::prometheus::report_dropped_events;
use crate::token::validate_token;
use crate::{
    api::{CaptureError, CaptureResponse, CaptureResponseCode},
    event::{EventFormData, EventQuery, ProcessedEvent, RawEvent},
    router, sinks,
    utils::uuid_v7,
};

#[instrument(
    skip_all,
    fields(
        token,
        batch_size,
        user_agent,
        content_encoding,
        content_type,
        version,
        compression
    )
)]
pub async fn event(
    state: State<router::State>,
    InsecureClientIp(ip): InsecureClientIp,
    meta: Query<EventQuery>,
    headers: HeaderMap,
    method: Method,
    body: Bytes,
) -> Result<Json<CaptureResponse>, CaptureError> {
    // content-type
    // user-agent

    let user_agent = headers
        .get("user-agent")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));
    let content_encoding = headers
        .get("content-encoding")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    let comp = match meta.compression {
        None => String::from("unknown"),
        Some(Compression::Gzip) => String::from("gzip"),
        Some(Compression::Unsupported) => String::from("unsupported"),
    };

    tracing::Span::current().record("user_agent", user_agent);
    tracing::Span::current().record("content_encoding", content_encoding);
    tracing::Span::current().record("version", meta.lib_version.clone());
    tracing::Span::current().record("compression", comp.as_str());
    tracing::Span::current().record("method", method.as_str());

    let events = match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/x-www-form-urlencoded" => {
            tracing::Span::current().record("content_type", "application/x-www-form-urlencoded");

            let input: EventFormData = serde_urlencoded::from_bytes(body.deref()).unwrap();
            let payload = base64::engine::general_purpose::STANDARD
                .decode(input.data)
                .unwrap();
            RawEvent::from_bytes(payload.into())
        }
        ct => {
            tracing::Span::current().record("content_type", ct);

            RawEvent::from_bytes(body)
        }
    }?;

    tracing::Span::current().record("batch_size", events.len());

    if events.is_empty() {
        return Err(CaptureError::EmptyBatch);
    }

    let token = extract_and_verify_token(&events).map_err(|err| {
        report_dropped_events("token_shape_invalid", events.len() as u64);
        err
    })?;

    tracing::Span::current().record("token", &token);

    counter!("capture_events_received_total").increment(events.len() as u64);

    let sent_at = meta.sent_at.and_then(|value| {
        let value_nanos: i128 = i128::from(value) * 1_000_000; // Assuming the value is in milliseconds, latest posthog-js releases
        if let Ok(sent_at) = OffsetDateTime::from_unix_timestamp_nanos(value_nanos) {
            if sent_at.year() > 2020 {
                // Could be lower if the input is in seconds
                return Some(sent_at);
            }
        }
        None
    });

    let context = ProcessingContext {
        lib_version: meta.lib_version.clone(),
        sent_at,
        token,
        now: state.timesource.current_time(),
        client_ip: ip.to_string(),
    };

    let billing_limited = state
        .billing
        .is_limited(context.token.as_str(), QuotaResource::Events)
        .await;

    if billing_limited {
        report_dropped_events("over_quota", events.len() as u64);

        // for v0 we want to just return ok 🙃
        // this is because the clients are pretty dumb and will just retry over and over and
        // over...
        //
        // for v1, we'll return a meaningful error code and error, so that the clients can do
        // something meaningful with that error
        return Ok(Json(CaptureResponse {
            status: CaptureResponseCode::Ok,
        }));
    }

    tracing::debug!(context=?context, events=?events, "decoded request");

    if let Err(err) = process_events(state.sink.clone(), &events, &context).await {
        report_dropped_events("process_events_error", events.len() as u64);
        tracing::log::warn!("rejected invalid payload: {}", err);
        return Err(err);
    }

    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
    }))
}

pub async fn options() -> Result<Json<CaptureResponse>, CaptureError> {
    Ok(Json(CaptureResponse {
        status: CaptureResponseCode::Ok,
    }))
}

#[instrument(skip_all)]
pub fn process_single_event(
    event: &RawEvent,
    context: &ProcessingContext,
) -> Result<ProcessedEvent, CaptureError> {
    if event.event.is_empty() {
        return Err(CaptureError::MissingEventName);
    }

    let data = serde_json::to_string(&event).map_err(|e| {
        tracing::error!("failed to encode data field: {}", e);
        CaptureError::NonRetryableSinkError
    })?;

    Ok(ProcessedEvent {
        uuid: event.uuid.unwrap_or_else(uuid_v7),
        distinct_id: event.extract_distinct_id()?,
        ip: context.client_ip.clone(),
        data,
        now: context.now.clone(),
        sent_at: context.sent_at,
        token: context.token.clone(),
    })
}

#[instrument(skip_all, fields(events = events.len()))]
pub fn extract_and_verify_token(events: &[RawEvent]) -> Result<String, CaptureError> {
    let distinct_tokens: HashSet<Option<String>> = HashSet::from_iter(
        events
            .iter()
            .map(RawEvent::extract_token)
            .filter(Option::is_some),
    );

    return match distinct_tokens.len() {
        0 => Err(CaptureError::NoTokenError),
        1 => match distinct_tokens.iter().last() {
            Some(Some(token)) => {
                validate_token(token)?;
                Ok(token.clone())
            }
            _ => Err(CaptureError::NoTokenError),
        },
        _ => Err(CaptureError::MultipleTokensError),
    };
}

#[instrument(skip_all, fields(events = events.len()))]
pub async fn process_events<'a>(
    sink: Arc<dyn sinks::Event + Send + Sync>,
    events: &'a [RawEvent],
    context: &'a ProcessingContext,
) -> Result<(), CaptureError> {
    let events: Vec<ProcessedEvent> = events
        .iter()
        .map(|e| process_single_event(e, context))
        .collect::<Result<Vec<ProcessedEvent>, CaptureError>>()?;

    tracing::debug!(events=?events, "processed {} events", events.len());

    if events.len() == 1 {
        sink.send(events[0].clone()).await
    } else {
        sink.send_batch(events).await
    }
}

#[cfg(test)]
mod tests {
    use crate::capture::extract_and_verify_token;
    use crate::event::RawEvent;
    use serde_json::json;
    use std::collections::HashMap;

    #[tokio::test]
    async fn all_events_have_same_token() {
        let events = vec![
            RawEvent {
                token: Some(String::from("hello")),
                distinct_id: Some(json!("testing")),
                uuid: None,
                event: String::new(),
                properties: HashMap::new(),
                timestamp: None,
                offset: None,
                set: Default::default(),
                set_once: Default::default(),
            },
            RawEvent {
                token: None,
                distinct_id: Some(json!("testing")),
                uuid: None,
                event: String::new(),
                properties: HashMap::from([(String::from("token"), json!("hello"))]),
                timestamp: None,
                offset: None,
                set: Default::default(),
                set_once: Default::default(),
            },
        ];

        let processed = extract_and_verify_token(&events);
        assert_eq!(processed.is_ok(), true, "{:?}", processed);
    }

    #[tokio::test]
    async fn all_events_have_different_token() {
        let events = vec![
            RawEvent {
                token: Some(String::from("hello")),
                distinct_id: Some(json!("testing")),
                uuid: None,
                event: String::new(),
                properties: HashMap::new(),
                timestamp: None,
                offset: None,
                set: Default::default(),
                set_once: Default::default(),
            },
            RawEvent {
                token: None,
                distinct_id: Some(json!("testing")),
                uuid: None,
                event: String::new(),
                properties: HashMap::from([(String::from("token"), json!("goodbye"))]),
                timestamp: None,
                offset: None,
                set: Default::default(),
                set_once: Default::default(),
            },
        ];

        let processed = extract_and_verify_token(&events);
        assert_eq!(processed.is_err(), true);
    }
}
