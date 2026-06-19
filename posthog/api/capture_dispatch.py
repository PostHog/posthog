"""Feature-flag-gated dispatch between legacy capture_internal and capture_v1_internal.

Temporary scaffolding for the legacy -> v1 capture transition. Each production
call site routes through ``capture_internal_routed`` (or ``capture_batch_internal_routed``
for the CSP batch path), gated by a per-``event_source`` boolean feature flag.

Teardown
--------
Once a source is fully cut over (flag at 100 % after bake period):

1. Repoint that call site to call ``capture_v1_internal`` directly and adopt its
   native ``CaptureV1Result`` / ``CaptureV1InternalError`` handling.
2. Delete the source's flag from PostHog and from ``EVENT_SOURCE_TO_FLAG``.

When all 9 sources are migrated, delete this module, ``CaptureRoutedError``,
``RoutedCaptureResult``, and the 9 flags in a single PR.  Legacy
``capture_internal`` is removed only after no source references it.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

import structlog
import posthoganalytics
from prometheus_client import Counter
from requests import HTTPError

from posthog.api.capture import (
    SESSION_RECORDING_EVENT_NAMES,
    CaptureInternalError,
    capture_batch_internal,
    capture_internal,
)
from posthog.api.capture_v1 import CaptureV1InternalError, capture_v1_batch_internal, capture_v1_internal

logger = structlog.get_logger(__name__)

# --------------------------------------------------------------------------- #
# Flag registry — one boolean flag per event_source tag
# --------------------------------------------------------------------------- #

EVENT_SOURCE_TO_FLAG: dict[str, str] = {
    "get_csp_report": "capture-v1-get-csp-report",
    "person_viewset": "capture-v1-person-viewset",
    "ee_ch_views_groups": "capture-v1-ee-ch-views-groups",
    "llm_analytics_evaluation": "capture-v1-llm-analytics-evaluation",
    "llm_analytics_tagger": "capture-v1-llm-analytics-tagger",
    "replay_vision": "capture-v1-replay-vision",
    "session_summary_events": "capture-v1-session-summary-events",
    "conversations_events": "capture-v1-conversations-events",
    "llm_prompt_management": "capture-v1-llm-prompt-management",
}

# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

CAPTURE_INTERNAL_ROUTED = Counter(
    "capture_internal_routed",
    "Dispatch decisions between legacy and v1 capture implementations.",
    labelnames=["event_source", "impl"],
)

CAPTURE_ROUTED_ERROR = Counter(
    "capture_internal_routed_error",
    "Errors from the routed capture path.",
    labelnames=["event_source", "impl", "error_type"],
)

# --------------------------------------------------------------------------- #
# Normalized error type
# --------------------------------------------------------------------------- #


class CaptureRoutedError(CaptureInternalError):
    """Normalized error raised by ``RoutedCaptureResult.raise_for_status()``.

    Carries a ``.status_code`` so call sites that previously read
    ``he.response.status_code`` from ``requests.HTTPError`` can use
    ``err.status_code`` instead.
    """

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# Normalized result type
# --------------------------------------------------------------------------- #


class RoutedCaptureResult:
    """Unified result from either legacy or v1 capture path."""

    __slots__ = ("status_code", "impl", "_error_message")

    def __init__(
        self,
        *,
        status_code: int,
        impl: Literal["legacy", "v1"],
        error_message: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        self.impl: Literal["legacy", "v1"] = impl
        self._error_message = error_message

    def raise_for_status(self) -> None:
        if self._error_message is not None:
            raise CaptureRoutedError(self._error_message, status_code=self.status_code)


# --------------------------------------------------------------------------- #
# Flag evaluation — fail-closed to legacy
# --------------------------------------------------------------------------- #


def _capture_v1_enabled(event_source: str, *, token: Optional[str] = None) -> bool:
    """Check whether v1 capture is enabled for this event_source.

    Uses ``only_evaluate_locally=True`` (backed by HyperCacheFlagProvider in
    Redis) to avoid a ``/decide`` network call per captured event.
    Falls back to legacy on any exception or missing flag definition.
    """
    flag_key = EVENT_SOURCE_TO_FLAG.get(event_source)
    if not flag_key:
        return False

    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag_key,
                token or "",
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.debug(
            "capture_v1_flag_eval_failed",
            event_source=event_source,
            flag_key=flag_key,
        )
        return False


# --------------------------------------------------------------------------- #
# Single-event dispatch
# --------------------------------------------------------------------------- #


def capture_internal_routed(
    *,
    event_source: str,
    token: str,
    event_name: str,
    distinct_id: str,
    timestamp: Any = None,
    properties: dict[str, Any],
    sent_at: Any = None,
    process_person_profile: bool = False,
    event_uuid: Optional[str] = None,
) -> RoutedCaptureResult:
    """Dispatch a single event to legacy or v1 capture based on feature flag.

    Signature-compatible with ``capture_internal``.

    Note: ``sent_at`` is forwarded on the legacy path only.
    ``capture_v1_internal`` does not accept ``sent_at`` (skew correction is
    handled server-side).  No current call site passes it.
    """
    # Replay events are unsupported by v1 — always use legacy.
    use_v1 = event_name not in SESSION_RECORDING_EVENT_NAMES and _capture_v1_enabled(event_source, token=token)

    impl: Literal["legacy", "v1"] = "v1" if use_v1 else "legacy"
    CAPTURE_INTERNAL_ROUTED.labels(event_source=event_source, impl=impl).inc()

    if use_v1:
        return _route_v1_single(
            event_source=event_source,
            token=token,
            event_name=event_name,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
            process_person_profile=process_person_profile,
            event_uuid=event_uuid,
        )

    return _route_legacy_single(
        event_source=event_source,
        token=token,
        event_name=event_name,
        distinct_id=distinct_id,
        timestamp=timestamp,
        properties=properties,
        sent_at=sent_at,
        process_person_profile=process_person_profile,
        event_uuid=event_uuid,
    )


def _route_legacy_single(
    *,
    event_source: str,
    token: str,
    event_name: str,
    distinct_id: str,
    timestamp: Any,
    properties: dict[str, Any],
    sent_at: Any,
    process_person_profile: bool,
    event_uuid: Optional[str],
) -> RoutedCaptureResult:
    try:
        resp = capture_internal(
            token=token,
            event_name=event_name,
            event_source=event_source,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
            sent_at=sent_at,
            process_person_profile=process_person_profile,
            event_uuid=event_uuid,
        )
        resp.raise_for_status()
        return RoutedCaptureResult(status_code=resp.status_code, impl="legacy")
    except HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        CAPTURE_ROUTED_ERROR.labels(event_source=event_source, impl="legacy", error_type="http").inc()
        return RoutedCaptureResult(
            status_code=status,
            impl="legacy",
            error_message=f"capture_internal HTTP error ({status}): {exc}",
        )
    except CaptureInternalError:
        raise
    except Exception as exc:
        CAPTURE_ROUTED_ERROR.labels(event_source=event_source, impl="legacy", error_type="transport").inc()
        return RoutedCaptureResult(
            status_code=0,
            impl="legacy",
            error_message=f"capture_internal transport error: {exc}",
        )


def _route_v1_single(
    *,
    event_source: str,
    token: str,
    event_name: str,
    distinct_id: str,
    timestamp: Any,
    properties: dict[str, Any],
    process_person_profile: bool,
    event_uuid: Optional[str],
) -> RoutedCaptureResult:
    try:
        result = capture_v1_internal(
            token=token,
            event_name=event_name,
            event_source=event_source,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
            process_person_profile=process_person_profile,
            event_uuid=event_uuid,
        )
        result.raise_for_status()
        return RoutedCaptureResult(status_code=result.status_code, impl="v1")
    except CaptureV1InternalError as exc:
        CAPTURE_ROUTED_ERROR.labels(event_source=event_source, impl="v1", error_type="v1_error").inc()
        return RoutedCaptureResult(
            status_code=getattr(exc, "status_code", 0),
            impl="v1",
            error_message=str(exc),
        )
    except CaptureInternalError:
        raise
    except Exception as exc:
        CAPTURE_ROUTED_ERROR.labels(event_source=event_source, impl="v1", error_type="transport").inc()
        return RoutedCaptureResult(
            status_code=0,
            impl="v1",
            error_message=f"capture_v1_internal transport error: {exc}",
        )


# --------------------------------------------------------------------------- #
# Batch dispatch (CSP report only)
# --------------------------------------------------------------------------- #


def capture_batch_internal_routed(
    *,
    events: list[dict[str, Any]],
    event_source: str,
    token: str,
    process_person_profile: bool = False,
) -> RoutedCaptureResult:
    """Dispatch a batch to legacy or v1 capture based on feature flag.

    Normalizes both paths to a single ``RoutedCaptureResult`` that raises on
    any per-event failure — matching the existing ``report.py`` semantics where
    the first ``HTTPError`` from any future propagates.
    """
    use_v1 = _capture_v1_enabled(event_source, token=token)
    impl: Literal["legacy", "v1"] = "v1" if use_v1 else "legacy"
    CAPTURE_INTERNAL_ROUTED.labels(event_source=event_source, impl=impl).inc()

    if use_v1:
        return _route_v1_batch(
            events=events,
            event_source=event_source,
            token=token,
            process_person_profile=process_person_profile,
        )

    return _route_legacy_batch(
        events=events,
        event_source=event_source,
        token=token,
        process_person_profile=process_person_profile,
    )


def _route_legacy_batch(
    *,
    events: list[dict[str, Any]],
    event_source: str,
    token: str,
    process_person_profile: bool,
) -> RoutedCaptureResult:
    try:
        futures = capture_batch_internal(
            events=events,
            event_source=event_source,
            token=token,
            process_person_profile=process_person_profile,
        )
        for future in futures:
            result = future.result()
            result.raise_for_status()
        return RoutedCaptureResult(status_code=204, impl="legacy")
    except HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        CAPTURE_ROUTED_ERROR.labels(event_source=event_source, impl="legacy", error_type="http").inc()
        return RoutedCaptureResult(
            status_code=status,
            impl="legacy",
            error_message=f"capture_batch_internal HTTP error ({status}): {exc}",
        )
    except CaptureInternalError:
        raise
    except Exception as exc:
        CAPTURE_ROUTED_ERROR.labels(event_source=event_source, impl="legacy", error_type="transport").inc()
        return RoutedCaptureResult(
            status_code=0,
            impl="legacy",
            error_message=f"capture_batch_internal transport error: {exc}",
        )


def _route_v1_batch(
    *,
    events: list[dict[str, Any]],
    event_source: str,
    token: str,
    process_person_profile: bool,
) -> RoutedCaptureResult:
    try:
        result = capture_v1_batch_internal(
            events=events,
            event_source=event_source,
            token=token,
            process_person_profile=process_person_profile,
        )
        result.raise_for_status()
        return RoutedCaptureResult(status_code=result.status_code, impl="v1")
    except CaptureV1InternalError as exc:
        CAPTURE_ROUTED_ERROR.labels(event_source=event_source, impl="v1", error_type="v1_error").inc()
        return RoutedCaptureResult(
            status_code=0,
            impl="v1",
            error_message=str(exc),
        )
    except CaptureInternalError:
        raise
    except Exception as exc:
        CAPTURE_ROUTED_ERROR.labels(event_source=event_source, impl="v1", error_type="transport").inc()
        return RoutedCaptureResult(
            status_code=0,
            impl="v1",
            error_message=f"capture_v1_batch_internal transport error: {exc}",
        )
