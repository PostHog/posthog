import structlog
from asgiref.sync import async_to_sync

from posthog.schema import SignalRemediation

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.alerts import _check_class_for_kind

logger = structlog.get_logger(__name__)

SOURCE_PRODUCT = "health_checks"
SOURCE_TYPE = "health_issue"


def emit_health_check_signal(issue: HealthIssue) -> bool:
    """Emit one Signals-inbox signal for a newly-firing health issue.

    Returns True if a signal was queued. A check opts in by overriding
    `HealthCheck.render_signal`; checks without an override return None and emit
    nothing. Runs in the synchronous processing thread, so the async facade is
    wrapped with `async_to_sync`. Never raises — a single bad issue must not
    break the orchestrator batch.
    """
    # Deferred import: keeps the signals product off the core import path and
    # avoids the facade's circular import back into the temporal stack.
    from products.signals.backend.facade.api import emit_signal  # noqa: PLC0415

    check_cls = _check_class_for_kind(issue.kind)
    if check_cls is None:
        return False

    content = check_cls.render_signal(issue)
    if content is None:  # check didn't opt in — no signal for this kind
        return False

    # The signal's remediation is the check's static human/agent guide, mapped onto the
    # SignalRemediation schema the facade validates. Checks without one emit no remediation.
    remediation = (
        SignalRemediation(human=check_cls.remediation.human, agent=check_cls.remediation.agent)
        if check_cls.remediation is not None
        else None
    )

    try:
        team = Team.objects.get(id=issue.team_id)
        async_to_sync(emit_signal)(
            team=team,
            source_product=SOURCE_PRODUCT,
            source_type=SOURCE_TYPE,
            source_id=str(issue.id),
            description=content.description,
            weight=content.weight,
            extra=content.extra,
            remediation=remediation,
        )
        return True
    except Exception as e:
        logger.exception("Failed to emit health-check signal", kind=issue.kind, issue_id=str(issue.id))
        capture_exception(e, additional_properties={"kind": issue.kind, "issue_id": str(issue.id)})
        return False
