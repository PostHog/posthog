//! Ingestion warnings for the OTLP trace endpoint (`/i/v0/ai/otel`).
//!
//! The endpoint's context projection lives with the OTEL code
//! (`crate::otel::attribution`) because it destructures OTLP types; see this
//! directory's module doc for the split.
//!
//! Unlike the analytics paths, every failure here happens after the token is
//! known, so it is attributable. What isn't emitted is therefore a policy
//! choice, not a limitation: quota and event-restriction rejections are
//! surfaced through billing and ops channels, and sink or serialization
//! failures are ours to fix.

use common_ingestion_warnings::{
    emit_request_warning, WarningEmitter, WarningRequestContext, WarningType, CAPTURE_AI_OTEL,
};
use serde_json::{json, Map};

use crate::api::CaptureError;

/// Which span cap a request tripped.
///
/// The raw cap bounds attribute-scanning cost before conversion; the AI cap
/// bounds what we'll ingest after non-AI spans are filtered out. A customer
/// over the raw cap has to batch smaller, one over the AI cap is sending too
/// many AI spans at once, so the two need telling apart.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SpanCapStage {
    Raw,
    Ai,
}

impl SpanCapStage {
    fn as_str(self) -> &'static str {
        match self {
            Self::Raw => "raw",
            Self::Ai => "ai",
        }
    }
}

/// Map an OTLP decode failure to the warning customers should see.
///
/// `parse_request` only ever returns the three variants matched below, but the
/// match is exhaustive over `CaptureError` and has no catch-all so that a new
/// failure mode there can't silently pick up the wrong warning here.
pub fn warning_for_otel_parse_error(err: &CaptureError) -> Option<WarningType> {
    match err {
        // The gzip decompressor raises this when the decompressed body would
        // exceed the endpoint's limit.
        CaptureError::EventTooBig(_) => Some(WarningType::MessageSizeTooLarge),
        // An unsupported content-encoding or content-type, a body that isn't
        // valid protobuf or JSON, or JSON that isn't an OTLP trace payload.
        CaptureError::RequestDecodingError(_) | CaptureError::RequestParsingError(_) => {
            Some(WarningType::InvalidAiPayload)
        }

        // Reachable only if `parse_request` grows a new failure mode: decide
        // warn-or-not there rather than defaulting to silence here.
        // `NonAiEventOnAiLane` and `AiEventTooBig` join them as structurally
        // unreachable: only `process_events` raises them, and this handler does
        // not call it.
        CaptureError::NonAiEventOnAiLane(_)
        | CaptureError::AiEventTooBig(_)
        | CaptureError::RequestHydrationError(_)
        | CaptureError::EmptyBatch
        | CaptureError::EmptyPayload
        | CaptureError::EmptyPayloadFiltered
        | CaptureError::NoTokenError
        | CaptureError::MultipleTokensError
        | CaptureError::TokenValidationError(_)
        | CaptureError::MissingEventName
        | CaptureError::MissingDistinctId
        | CaptureError::InvalidCookielessMode
        | CaptureError::InvalidTimestamp
        | CaptureError::MissingSnapshotData
        | CaptureError::MissingSessionId
        | CaptureError::MissingWindowId
        | CaptureError::InvalidSessionId
        | CaptureError::BillingLimit
        | CaptureError::RateLimited
        | CaptureError::GlobalRateLimitExceeded()
        | CaptureError::RetryableSinkError
        | CaptureError::NonRetryableSinkError
        | CaptureError::ServiceUnavailable(_)
        | CaptureError::BodyReadTimeout
        | CaptureError::InternalError(_) => None,
    }
}

/// Emit the warning for a request whose OTLP body could not be read.
///
/// `count = 1`: the span count is unknowable when the payload didn't parse, and
/// a zero would read as "nothing happened" in the v2 table.
///
/// `format` is what the handler resolved the content-type to, and it is the
/// detail that makes the warning actionable: `unknown` says the content-type
/// itself was wrong, while a named format says the body didn't match the type
/// the client claimed. The decode error's own message is deliberately left out;
/// it can embed arbitrary payload bytes, and this lands in a customer-visible
/// column.
pub fn emit_otel_parse_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    err: &CaptureError,
    format: &str,
) {
    let Some(warning) = warning_for_otel_parse_error(err) else {
        return;
    };
    let mut details = Map::new();
    details.insert("format".to_string(), json!(format));

    emit_request_warning(emitter, request, CAPTURE_AI_OTEL, warning, details, 1);
}

/// Emit the warning for a request rejected for carrying too many spans.
///
/// `count` charges every span in the request: the cap check runs before any
/// span is sent, so the whole payload was rejected.
pub fn emit_span_cap_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    stage: SpanCapStage,
    span_count: usize,
    limit: usize,
) {
    let mut details = Map::new();
    details.insert("stage".to_string(), json!(stage.as_str()));
    details.insert("spanCount".to_string(), json!(span_count));
    details.insert("limit".to_string(), json!(limit));

    emit_request_warning(
        emitter,
        request,
        CAPTURE_AI_OTEL,
        WarningType::InvalidAiPayload,
        details,
        span_count as u64,
    );
}

/// Emit the warning for spans shed for exceeding the deployment's per-event
/// size ceiling.
///
/// This is the second warning here that accompanies a 200. The export is not
/// refused, because an OTEL collector retries a rejected export and would stall
/// behind a span that can never fit — so the offending spans are shed and the
/// rest publish. That trade makes the loss invisible in the response, which is
/// what this warning exists to correct.
///
/// `count` charges only the spans that were shed; the others landed.
pub fn emit_span_too_big_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    dropped_spans: usize,
    limit: u64,
) {
    let mut details = Map::new();
    details.insert("droppedSpans".to_string(), json!(dropped_spans));
    details.insert("limit".to_string(), json!(limit));

    emit_request_warning(
        emitter,
        request,
        CAPTURE_AI_OTEL,
        WarningType::MessageSizeTooLarge,
        details,
        dropped_spans as u64,
    );
}

/// Emit the warning for an export whose spans all filtered out as non-AI.
///
/// This is the one warning here that accompanies a 200. The OTLP contract gives
/// us no way to say "accepted, ingested nothing", so without this the customer
/// sees success and no events, with nothing to correlate. Mixed batches are
/// expected and are not warned about; only a request that produced no AI events
/// at all is.
///
/// `count` charges the spans that were sent, since none of them landed.
pub fn emit_no_ai_spans_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    raw_span_count: usize,
) {
    let mut details = Map::new();
    details.insert("rawSpanCount".to_string(), json!(raw_span_count));

    emit_request_warning(
        emitter,
        request,
        CAPTURE_AI_OTEL,
        WarningType::NoAiSpansIngested,
        details,
        raw_span_count as u64,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_ingestion_warnings::test_support::CollectingEmitter;
    use common_ingestion_warnings::UNKNOWN_ATTRIBUTION;
    use rstest::rstest;

    fn request() -> WarningRequestContext {
        WarningRequestContext {
            token: "tok".to_string(),
            lib: "opentelemetry-js".to_string(),
            lib_version: "2.0.0".to_string(),
            path: "/i/v0/ai/otel".to_string(),
        }
    }

    #[rstest]
    #[case::oversize(
        CaptureError::EventTooBig("too big".to_string()),
        Some(WarningType::MessageSizeTooLarge)
    )]
    #[case::bad_content_type(
        CaptureError::RequestDecodingError("Content-Type must be".to_string()),
        Some(WarningType::InvalidAiPayload)
    )]
    #[case::bad_protobuf(
        CaptureError::RequestParsingError("Invalid protobuf".to_string()),
        Some(WarningType::InvalidAiPayload)
    )]
    // Ours to fix, or unreachable from parse_request; see the mapper's None arms.
    #[case::internal(CaptureError::InternalError("boom".to_string()), None)]
    #[case::sink(CaptureError::RetryableSinkError, None)]
    #[case::billing(CaptureError::BillingLimit, None)]
    fn parse_errors_map_only_to_payload_problems(
        #[case] err: CaptureError,
        #[case] expected: Option<WarningType>,
    ) {
        assert_eq!(warning_for_otel_parse_error(&err), expected);
    }

    // Same trust chain the legacy mapper pins: a type that is not
    // capture-produced gets demoted to a generic client warning by the nodejs
    // consumer, and one reachable by both routes breaks the common crate's
    // one-route invariant. Both fail silently in production.
    #[test]
    fn emitted_warnings_are_trusted_and_single_routed() {
        let emitter = CollectingEmitter::default();
        emit_otel_parse_warning(
            Some(&emitter),
            &request(),
            &CaptureError::RequestParsingError("bad".to_string()),
            "protobuf",
        );
        emit_span_cap_warning(Some(&emitter), &request(), SpanCapStage::Raw, 1001, 1000);
        emit_no_ai_spans_warning(Some(&emitter), &request(), 4);

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 3);
        for warning in emitted {
            assert_eq!(warning.source, CAPTURE_AI_OTEL);
            assert!(
                warning.warning.capture_produced(),
                "{:?} is not on the consumer trust allowlist",
                warning.warning
            );
            assert!(
                WarningType::from_tag(warning.warning.as_str()).is_none(),
                "{:?} must not also be tag-routed",
                warning.warning
            );
        }
    }

    #[test]
    fn parse_warning_reports_the_resolved_format_not_the_error_message() {
        let emitter = CollectingEmitter::default();
        emit_otel_parse_warning(
            Some(&emitter),
            &request(),
            &CaptureError::RequestParsingError("Invalid protobuf: buffer underflow".to_string()),
            "unknown",
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        let warning = &emitted[0];
        assert_eq!(warning.warning, WarningType::InvalidAiPayload);
        assert_eq!(warning.count, 1);
        assert_eq!(warning.extra_details.get("format"), Some(&json!("unknown")));
        // The decode message can embed payload bytes, so it must never ride along.
        assert!(!warning.extra_details.contains_key("message"));
        assert!(!warning.extra_details.contains_key("reason"));
        assert_eq!(warning.token, "tok");
        assert_eq!(
            warning.extra_details.get("lib"),
            Some(&json!("opentelemetry-js"))
        );
    }

    #[rstest]
    #[case::raw(SpanCapStage::Raw, 1001, 1000, "raw")]
    #[case::ai(SpanCapStage::Ai, 101, 100, "ai")]
    fn span_cap_warning_charges_every_span_and_names_the_stage(
        #[case] stage: SpanCapStage,
        #[case] span_count: usize,
        #[case] limit: usize,
        #[case] expected_stage: &str,
    ) {
        let emitter = CollectingEmitter::default();
        emit_span_cap_warning(Some(&emitter), &request(), stage, span_count, limit);

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        let warning = &emitted[0];
        assert_eq!(warning.warning, WarningType::InvalidAiPayload);
        assert_eq!(warning.count, span_count as u64);
        assert_eq!(
            warning.extra_details.get("stage"),
            Some(&json!(expected_stage))
        );
        assert_eq!(
            warning.extra_details.get("spanCount"),
            Some(&json!(span_count))
        );
        assert_eq!(warning.extra_details.get("limit"), Some(&json!(limit)));
    }

    #[test]
    fn no_ai_spans_warning_charges_the_spans_that_were_sent() {
        let emitter = CollectingEmitter::default();
        emit_no_ai_spans_warning(Some(&emitter), &request(), 7);

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        let warning = &emitted[0];
        assert_eq!(warning.warning, WarningType::NoAiSpansIngested);
        assert_eq!(warning.count, 7);
        assert_eq!(warning.extra_details.get("rawSpanCount"), Some(&json!(7)));
    }

    #[test]
    fn unknown_attribution_still_emits() {
        let emitter = CollectingEmitter::default();
        let unattributed = WarningRequestContext {
            token: "tok".to_string(),
            lib: UNKNOWN_ATTRIBUTION.to_string(),
            lib_version: UNKNOWN_ATTRIBUTION.to_string(),
            path: "/i/v0/ai/otel".to_string(),
        };

        emit_otel_parse_warning(
            Some(&emitter),
            &unattributed,
            &CaptureError::RequestDecodingError("nope".to_string()),
            "unknown",
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        assert_eq!(
            emitted[0].extra_details.get("lib"),
            Some(&json!(UNKNOWN_ATTRIBUTION))
        );
    }

    #[test]
    fn no_emitter_is_a_silent_no_op() {
        emit_otel_parse_warning(
            None,
            &request(),
            &CaptureError::RequestParsingError("bad".to_string()),
            "json",
        );
        emit_span_cap_warning(None, &request(), SpanCapStage::Ai, 101, 100);
        emit_no_ai_spans_warning(None, &request(), 3);
    }
}
