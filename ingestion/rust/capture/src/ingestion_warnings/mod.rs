//! Capture's ingestion-warning conversion layer.
//!
//! Normalizing lives here rather than in `common_ingestion_warnings` so that
//! crate never learns capture's event shapes: it takes concrete strings and
//! stamps them.
//!
//! The split inside this directory is between two different jobs:
//!
//! * **Context projections** turn one pipeline's own request type into a
//!   [`WarningRequestContext`]. Every capture pipeline learns the client SDK
//!   differently, and the differences are permanent, not transitional, so a
//!   projection is inseparable from the types it reads. Those live *with their
//!   pipeline*: v1's is [`crate::v1::context::RequestContext::warning_context`],
//!   built from the `PostHog-Sdk-Info` header it requires. Legacy's is the
//!   exception below, because legacy has no subtree of its own: it is spread
//!   across `v0_endpoint`, `v0_request`, `events/`, and `payload/`.
//! * **Emit helpers and type mappers** decide which warning a failure becomes
//!   and which details ride along. Every pipeline's details land in one
//!   customer-facing table, and a reader of that table cannot tell which
//!   pipeline served a request, so the payloads must not drift apart. Keeping
//!   them in sibling files here is what makes drift visible in review.
//!
//! This module itself holds only what more than one pipeline genuinely shares.

pub mod ai;
pub mod legacy;
pub mod otel;
pub mod replay;

use std::collections::HashSet;

use common_ingestion_warnings::{
    emit_request_warning, WarningEmitter, WarningRequestContext, WarningSource, WarningType,
    UNKNOWN_ATTRIBUTION,
};
use common_types::{EventWithLibraryInfo, RawEvent};
use serde_json::{json, Map};
use uuid::Uuid;

/// Max accepted length of a client-supplied `$lib` or `$lib_version`, matching
/// the bound v1 puts on the `PostHog-Sdk-Info` header (real values are ~20
/// bytes). Oversized values are treated as absent rather than truncated: they
/// would otherwise ride into every warning payload for the batch and into the
/// `Debug` output of [`crate::v0_request::ProcessingContext`], which the legacy
/// path logs several times per request when chatty debug is on.
pub const MAX_SDK_ATTRIBUTION_LEN: usize = 200;

/// SDK identity as reported by a batch, for attribution only.
///
/// Both fields are unvalidated client input. Nothing routes on them.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SdkAttribution {
    pub lib: Option<String>,
    pub lib_version: Option<String>,
}

impl SdkAttribution {
    /// Take attribution from the first event of a batch.
    ///
    /// One batch is one SDK in every real client: batching is a client-side
    /// buffer flush, so events in it share a `$lib`. Scanning further to
    /// reconcile disagreement would cost a pass over the batch on the hot path
    /// to improve a field that is only ever displayed.
    pub fn from_first_event(events: &[RawEvent]) -> Self {
        let Some(info) = events.first().and_then(|e| e.extract_library_info()) else {
            return Self::default();
        };
        Self {
            lib: within_bound(info.name),
            lib_version: info.version.and_then(within_bound),
        }
    }
}

/// Drop an attribution value longer than [`MAX_SDK_ATTRIBUTION_LEN`] so it lands
/// on the unknown fallback instead of riding into every warning for the request.
pub(crate) fn within_bound(value: String) -> Option<String> {
    (value.len() <= MAX_SDK_ATTRIBUTION_LEN).then_some(value)
}

/// Bound a client-supplied value being copied into a warning's details.
///
/// Same budget and same reason as [`MAX_SDK_ATTRIBUTION_LEN`]: details ride into
/// every warning message and land in a customer-visible table, and nothing
/// downstream length-limits them, so an oversized event name or part name would
/// inflate Kafka messages and warning storage.
///
/// Unlike attribution, these values name the thing the customer has to fix, so
/// an oversized one is truncated rather than dropped. Truncation is marked, and
/// respects char boundaries so a multi-byte name can't be cut mid-character.
pub(crate) fn bounded_detail(value: &str) -> String {
    if value.len() <= MAX_SDK_ATTRIBUTION_LEN {
        return value.to_string();
    }
    let end = (0..=MAX_SDK_ATTRIBUTION_LEN)
        .rev()
        .find(|&i| value.is_char_boundary(i))
        .unwrap_or(0);
    format!("{}…", &value[..end])
}

/// Stamp [`UNKNOWN_ATTRIBUTION`] rather than dropping the key, so every warning
/// has the same shape whether or not the client identified itself.
pub(crate) fn unknown_if_missing(value: Option<&str>) -> String {
    match value {
        Some(v) if !v.trim().is_empty() => v.to_string(),
        _ => UNKNOWN_ATTRIBUTION.to_string(),
    }
}

/// Emit the `high_volume_distinct_id` warning for one batch's rate-limited
/// events. Shared by the v1 and legacy rate limiter stages, which differ only in
/// their [`WarningSource`] — the payload must not drift between them, since a
/// reader of the v2 table can't tell which pipeline served a request.
///
/// `distinct_id` is included only when the batch had exactly one hot key; with
/// several it would be an arbitrary pick, and `distinctIdCount` already says how
/// many there were. The value needs no size bounding here: both pipelines drop
/// oversized distinct_ids before the limiter runs.
pub fn emit_rate_limit_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    source: WarningSource,
    limited_distinct_ids: &HashSet<&str>,
    limited_event_count: u64,
) {
    let mut details = Map::new();
    details.insert(
        "distinctIdCount".to_string(),
        json!(limited_distinct_ids.len()),
    );
    if let [distinct_id] = limited_distinct_ids.iter().copied().collect::<Vec<_>>()[..] {
        details.insert("distinctId".to_string(), json!(distinct_id));
    }

    emit_request_warning(
        emitter,
        request,
        source,
        WarningType::HighVolumeDistinctId,
        details,
        limited_event_count,
    );
}

/// Emit the `distinct_id_truncated` warning for one batch's events whose
/// distinct_id was cut down to the 200-char cap at extraction. The events were
/// ingested (modified, not dropped), which is why v1 has no counterpart: it
/// rejects oversized ids outright as `distinct_id_too_large`. Shared by the
/// legacy analytics and replay pipelines, which differ only in their
/// [`WarningSource`], so that the payload cannot drift between them.
///
/// Identifier details are included only when the batch had exactly one
/// truncated event; with several they would be an arbitrary pick, and `count`
/// already carries the volume. The truncated value is at most 200 chars, so
/// it needs no bounding of its own; `distinctIdLength` is the original char
/// count, telling the customer how far over the cap they were.
pub fn emit_distinct_id_truncated_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    source: WarningSource,
    sample: Option<(String, usize, Uuid)>,
    count: u64,
) {
    let mut details = Map::new();
    if let Some((distinct_id, original_chars, event_uuid)) = sample {
        details.insert("distinctId".to_string(), json!(distinct_id));
        details.insert("distinctIdLength".to_string(), json!(original_chars));
        details.insert("eventUuid".to_string(), json!(event_uuid));
    }

    emit_request_warning(
        emitter,
        request,
        source,
        WarningType::DistinctIdTruncated,
        details,
        count,
    );
}

/// A `RawEvent` carrying only `properties`, for the attribution tests in this
/// module and its children.
#[cfg(test)]
pub(crate) fn raw_event(properties: serde_json::Value) -> RawEvent {
    RawEvent {
        event: "$pageview".to_string(),
        properties: properties
            .as_object()
            .expect("test properties must be an object")
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
        ..Default::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn first_event_supplies_attribution_for_the_whole_batch() {
        let events = vec![
            raw_event(json!({"$lib": "web", "$lib_version": "1.2.3"})),
            raw_event(json!({"$lib": "posthog-python", "$lib_version": "9.9.9"})),
        ];
        assert_eq!(
            SdkAttribution::from_first_event(&events),
            SdkAttribution {
                lib: Some("web".to_string()),
                lib_version: Some("1.2.3".to_string()),
            }
        );
    }
}
