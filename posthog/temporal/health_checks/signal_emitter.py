import asyncio
from dataclasses import dataclass

import structlog
from asgiref.sync import async_to_sync

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.alerts import _check_class_for_kind
from posthog.temporal.health_checks.framework import _SEVERITY_PRIORITY

from products.signals.backend.contracts import SignalRemediation

logger = structlog.get_logger(__name__)

SOURCE_PRODUCT = "health_checks"
SOURCE_TYPE = "health_issue"


@dataclass(frozen=True)
class _PreparedSignal:
    """A health issue resolved into the arguments `emit_signal` needs."""

    issue: HealthIssue
    description: str
    weight: float
    extra: dict
    remediation: SignalRemediation | None


def _prepare_signal(issue: HealthIssue) -> _PreparedSignal | None:
    """Resolve a health issue into its signal payload, or None to emit nothing.

    A check opts in by overriding `HealthCheck.render_signal`; checks without an
    override return None and emit nothing. Pure and cheap (no IO). Never raises —
    a single bad issue must not break the orchestrator batch.
    """
    try:
        check_cls = _check_class_for_kind(issue.kind)
        if check_cls is None:
            return None

        content = check_cls.render_signal(issue)
        if content is None:  # check didn't opt in
            return None

        # Static human/agent guide, with priority derived from the issue's severity.
        remediation = (
            SignalRemediation(
                human=check_cls.remediation.human,
                agent=check_cls.remediation.agent,
                priority=_SEVERITY_PRIORITY.get(issue.severity),
            )
            if check_cls.remediation is not None
            else None
        )
        return _PreparedSignal(
            issue=issue,
            description=content.description,
            weight=content.weight,
            extra=content.extra,
            remediation=remediation,
        )
    except Exception as e:
        logger.exception("Failed to prepare health-check signal", kind=issue.kind, issue_id=str(issue.id))
        capture_exception(e, additional_properties={"kind": issue.kind, "issue_id": str(issue.id)})
        return None


def emit_health_check_signals(issues: list[HealthIssue]) -> int:
    """Emit Signals-inbox signals for a batch of newly-firing health issues.

    Returns the number of signals queued. Resolves every issue up front, fetches all
    teams in one query, then fires the emissions concurrently rather than blocking the
    processing thread on each one's serial IO. Never raises — a single bad issue must
    not break the orchestrator batch.
    """
    # Deferred import: keeps the signals product off the core import path and
    # avoids the facade's circular import back into the temporal stack.
    from products.signals.backend.facade.api import emit_signal  # noqa: PLC0415

    resolved = (_prepare_signal(issue) for issue in issues)
    prepared = [signal for signal in resolved if signal is not None]
    if not prepared:
        return 0

    # One query for the whole batch, with `organization` joined so `emit_signal` doesn't refetch it.
    teams = Team.objects.select_related("organization").in_bulk([signal.issue.team_id for signal in prepared])

    async def _emit_one(signal: _PreparedSignal) -> bool:
        team = teams.get(signal.issue.team_id)
        if team is None:
            logger.warning(
                "Team missing for health-check signal", issue_id=str(signal.issue.id), team_id=signal.issue.team_id
            )
            return False
        await emit_signal(
            team=team,
            source_product=SOURCE_PRODUCT,
            source_type=SOURCE_TYPE,
            source_id=str(signal.issue.id),
            description=signal.description,
            weight=signal.weight,
            extra=signal.extra,
            remediation=signal.remediation,
        )
        return True

    async def _emit_all() -> list[bool | BaseException]:
        return await asyncio.gather(*(_emit_one(signal) for signal in prepared), return_exceptions=True)

    queued = 0
    for signal, result in zip(prepared, async_to_sync(_emit_all)()):
        if isinstance(result, BaseException):
            logger.exception(
                "Failed to emit health-check signal",
                kind=signal.issue.kind,
                issue_id=str(signal.issue.id),
                exc_info=result,
            )
            capture_exception(
                result, additional_properties={"kind": signal.issue.kind, "issue_id": str(signal.issue.id)}
            )
        elif result:
            queued += 1
    return queued
