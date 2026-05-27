from typing import Literal

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck
from posthog.temporal.health_checks.registry import _DETECT_FNS, ensure_registry_loaded

logger = structlog.get_logger(__name__)


EVENT_FIRING = "$health_check_issue_firing"
EVENT_RESOLVED = "$health_check_issue_resolved"


# FUTURE: this module is the seam where a Signals-style inbox can plug in.
# Health-check transitions already carry a uniform envelope (kind / severity /
# title / summary / link / payload); a Signals integration can read from the
# same event stream — keep that envelope stable as new fields are added.


def _check_class_for_kind(kind: str) -> type[HealthCheck] | None:
    # The registry only stores instance-bound detect callables, but every
    # HealthCheck subclass binds `cls()` so the underlying class is reachable
    # via the bound method's `__self__`. Ensure the registry is loaded so this
    # works when called outside the orchestrator's primary code path.
    ensure_registry_loaded()
    fn = _DETECT_FNS.get(kind)
    if fn is None:
        return None
    instance = getattr(fn, "__self__", None)
    if instance is None:
        return None
    return type(instance)


def _render(issue: HealthIssue) -> AlertContent:
    check_cls = _check_class_for_kind(issue.kind)
    if check_cls is None:
        return AlertContent(title=issue.kind, summary=f"{issue.kind} ({issue.severity})", link="/health")
    return check_cls.render_alert(issue)


def emit_health_check_alert(issue: HealthIssue, *, status: Literal["firing", "resolved"]) -> bool:
    """Emit one $health_check_issue_{firing,resolved} event for a transition.

    Returns True if the event was produced. Failures (render or Kafka) are
    swallowed and reported to Sentry so a single bad issue cannot break the
    orchestrator batch.
    """
    try:
        content = _render(issue)
        produce_internal_event(
            team_id=issue.team_id,
            event=InternalEventEvent(
                event=EVENT_FIRING if status == "firing" else EVENT_RESOLVED,
                distinct_id=f"team_{issue.team_id}",
                properties={
                    "kind": issue.kind,
                    "severity": issue.severity,
                    "issue_id": str(issue.id),
                    "title": content.title,
                    "summary": content.summary,
                    "link": content.link,
                    "payload": issue.payload,
                },
            ),
        )
        return True
    except Exception as e:
        logger.exception(
            "Failed to emit health-check alert",
            kind=issue.kind,
            issue_id=str(issue.id),
            status=status,
            error=str(e),
        )
        capture_exception(e, additional_properties={"kind": issue.kind, "issue_id": str(issue.id), "status": status})
        return False
