//! Request-scoped attribution shared by every warning one request produces.
//!
//! This is the envelope-producer seam: services that know only API tokens
//! (capture) stamp per-request attribution here and emit through
//! [`WarningEmitter`]. Row producers do not belong here — personhog leader
//! commits terminal rows via [`crate::serializer::Warning::into_row`], with a
//! `team_id` and no request behind it.

use serde_json::{Map, Value};

use crate::{WarningEmitter, WarningSource, WarningType};

/// Value stamped for attribution a request genuinely doesn't carry.
///
/// SDK attribution is client-supplied, so any request can omit it: a bare
/// `POST /e/` with no `$lib`, a proxy that strips properties, a batch whose
/// first event is minimal. Emitting the key as `"unknown"` rather than
/// omitting it keeps every warning's payload the same shape, which is what
/// makes the v2 detail columns groupable — `GROUP BY lib` silently loses rows
/// where the key is absent, and a reader can't tell "no SDK reported" from
/// "this emit site forgot to stamp it".
pub const UNKNOWN_ATTRIBUTION: &str = "unknown";

/// Per-request attribution for warnings, resolved once by the caller.
///
/// Fields are plain owned strings, deliberately: each capture path reports SDK
/// identity differently (v1 reads request-level context, the legacy path takes
/// it from the first event of the batch, replay and AI have their own quirks),
/// so normalizing — including substituting [`UNKNOWN_ATTRIBUTION`] — is the
/// caller's job. Keeping `Option` and event introspection out of this crate is
/// what stops it from growing per-caller knowledge of capture's event shapes.
#[derive(Debug, Clone)]
pub struct WarningRequestContext {
    /// The offending event's API token. The consumer resolves it to a team, and
    /// it scopes the emitter's throttle.
    pub token: String,
    /// SDK name, e.g. `web`, `posthog-python`.
    pub lib: String,
    /// SDK version as reported, e.g. `1.234.5`.
    pub lib_version: String,
    /// Request path the warning came in on, e.g. `/i/v0/e/`.
    pub path: String,
}

impl WarningRequestContext {
    /// Attribution as warning details. camelCase to match the v2 `DEFAULT`
    /// extractors' expectations for entity keys.
    fn as_details(&self) -> [(&'static str, &str); 3] {
        [
            ("lib", self.lib.as_str()),
            ("libVersion", self.lib_version.as_str()),
            ("path", self.path.as_str()),
        ]
    }
}

/// Emit one warning with request attribution merged into `extra_details`.
///
/// `emitter` is an `Option` because warnings are opt-in per deployment and
/// every call site would otherwise repeat the same short-circuit; `None` is a
/// no-op, never an error. Attribution keys win over `extra_details` on
/// collision, for the same reason the serializer's injected row keys do: a
/// caller cannot be allowed to misreport where a warning came from.
///
/// Use this for warnings capture emits directly (see
/// [`WarningType::DIRECT_EMIT`]) as well as for tag-derived ones — the route
/// that picks the [`WarningType`] is independent of stamping attribution onto
/// it.
pub fn emit_request_warning(
    emitter: Option<&dyn WarningEmitter>,
    request: &WarningRequestContext,
    source: WarningSource,
    warning: WarningType,
    extra_details: Map<String, Value>,
    count: u64,
) {
    let Some(emitter) = emitter else {
        return;
    };

    let mut details = extra_details;
    for (key, value) in request.as_details() {
        details.insert(key.to_string(), Value::String(value.to_string()));
    }

    emitter.emit(request.token.clone(), source, warning, details, count);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::CollectingEmitter;
    use crate::CAPTURE_V1_ANALYTICS;

    fn context() -> WarningRequestContext {
        WarningRequestContext {
            token: "tok".to_string(),
            lib: "web".to_string(),
            lib_version: "1.2.3".to_string(),
            path: "/i/v0/e/".to_string(),
        }
    }

    #[test]
    fn no_emitter_is_a_silent_no_op() {
        // The whole point of the Option: a deployment with warnings off must
        // not need every call site to remember to check.
        emit_request_warning(
            None,
            &context(),
            CAPTURE_V1_ANALYTICS,
            WarningType::HighVolumeDistinctId,
            Map::new(),
            1,
        );
    }

    #[test]
    fn attribution_is_stamped_and_wins_over_caller_details() {
        let emitter = CollectingEmitter::default();
        let mut extra = Map::new();
        extra.insert("distinctId".to_string(), Value::String("abc".to_string()));
        // A caller trying to relabel where the warning came from must not win.
        extra.insert("lib".to_string(), Value::String("spoofed".to_string()));

        emit_request_warning(
            Some(&emitter),
            &context(),
            CAPTURE_V1_ANALYTICS,
            WarningType::HighVolumeDistinctId,
            extra,
            7,
        );

        let emitted = emitter.emitted();
        assert_eq!(emitted.len(), 1);
        let w = &emitted[0];
        assert_eq!(w.token, "tok");
        assert_eq!(w.warning, WarningType::HighVolumeDistinctId);
        assert_eq!(w.count, 7);
        assert_eq!(w.extra_details["lib"], Value::String("web".to_string()));
        assert_eq!(
            w.extra_details["libVersion"],
            Value::String("1.2.3".to_string())
        );
        assert_eq!(
            w.extra_details["path"],
            Value::String("/i/v0/e/".to_string())
        );
        assert_eq!(
            w.extra_details["distinctId"],
            Value::String("abc".to_string())
        );
    }
}
