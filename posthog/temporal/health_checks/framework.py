from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from posthog.clickhouse.query_tagging import Product
from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY, HealthExecutionPolicy
from posthog.temporal.health_checks.models import DEFAULT_ACTIVE_SINCE_DAYS, HealthCheckResult
from posthog.temporal.health_checks.registry import _DETECT_FNS, HEALTH_CHECKS, ensure_registry_loaded

from products.signals.backend.enums import ReportPriority

# Severity → signal weight. Critical issues hit weight 1.0, which triggers the
# Signals summary pipeline; lower severities rank below in the inbox feed.
_SEVERITY_WEIGHT: dict[str, float] = {
    HealthIssue.Severity.CRITICAL: 1.0,
    HealthIssue.Severity.WARNING: 0.7,
    HealthIssue.Severity.INFO: 0.4,
}

# Severity → suggested report priority, carried on a signal's remediation. Kept beside
# `_SEVERITY_WEIGHT` so the two severity mappings stay in sync.
_SEVERITY_PRIORITY: dict[str, ReportPriority] = {
    HealthIssue.Severity.CRITICAL: ReportPriority.P1,
    HealthIssue.Severity.WARNING: ReportPriority.P2,
    HealthIssue.Severity.INFO: ReportPriority.P3,
}


@dataclass(frozen=True)
class AlertContent:
    """User-facing description of a fired health-check alert.

    Health checks override `HealthCheck.render_alert` to produce one of
    these. The fields are embedded into `$health_check_issue_firing` and
    `$health_check_issue_resolved` event properties, where HogFunction
    templates pick them up as `event.properties.title`, etc.
    """

    title: str
    summary: str
    # Relative path inside the PostHog app (e.g. "/health/sdk-health").
    # HogFunction templates concatenate this onto {project.url}.
    link: str


@dataclass(frozen=True)
class Remediation:
    """How to resolve issues of a given health-check kind.

    Static per kind (not per issue), so it lives as a constant on the check.
    `human` is the UI-oriented fix shown to people and sent to alert
    destinations; `agent` is what an agent should do to investigate and — where
    the fix lives in the user's codebase — apply it directly.

    Both fields are run through `inspect.cleandoc` at construction, so checks
    can write naturally-indented triple-quoted strings and every reader sees
    clean, dedented prose.
    """

    human: str
    agent: str

    def __post_init__(self) -> None:
        # Frozen dataclass — normalize in place via object.__setattr__.
        object.__setattr__(self, "human", inspect.cleandoc(self.human))
        object.__setattr__(self, "agent", inspect.cleandoc(self.agent))


@dataclass(frozen=True)
class SignalContent:
    """An inbox signal rendered from a newly-firing health issue.

    Checks opt into the Signals inbox by overriding `HealthCheck.render_signal`
    to return one of these. `description` is what a reviewer reads in the feed;
    `weight` ranks it (see `_SEVERITY_WEIGHT`); `extra` is product metadata that
    must satisfy the `health_checks`/`health_issue` schema variant in
    `frontend/src/queries/schema/schema-signals.ts`.

    The signal's remediation is not carried here — it's the check's static
    `Remediation` (human/agent), which the signal emitter reads directly and
    maps onto the signal's top-level `remediation` field.
    """

    description: str
    weight: float
    extra: dict[str, Any]


# Bounds on `issue.payload` before it lands in a signal's `extra`, which the Signals pipeline
# renders verbatim into LLM context — an unbounded check payload must not blow up the prompt.
_MAX_PAYLOAD_LIST_ITEMS = 20
_MAX_PAYLOAD_STR_LEN = 500
_MAX_PAYLOAD_DEPTH = 3


def _bounded_payload_value(value: Any, depth: int = 0) -> Any:
    """Recursively cap list length, string length, and nesting depth of a payload value."""
    if isinstance(value, str):
        if len(value) <= _MAX_PAYLOAD_STR_LEN:
            return value
        return f"{value[:_MAX_PAYLOAD_STR_LEN]}… (truncated)"
    if isinstance(value, list):
        if depth >= _MAX_PAYLOAD_DEPTH:
            return f"[{len(value)} items]"
        bounded = [_bounded_payload_value(item, depth + 1) for item in value[:_MAX_PAYLOAD_LIST_ITEMS]]
        if len(value) > _MAX_PAYLOAD_LIST_ITEMS:
            bounded.append(f"… (+{len(value) - _MAX_PAYLOAD_LIST_ITEMS} more)")
        return bounded
    if isinstance(value, dict):
        if depth >= _MAX_PAYLOAD_DEPTH:
            return f"{{{len(value)} keys}}"
        return {key: _bounded_payload_value(item, depth + 1) for key, item in value.items()}
    return value


def build_signal_extra(issue: HealthIssue, *, title: str, summary: str, link: str) -> dict[str, Any]:
    """Assemble the `extra` envelope for a health-check signal.

    Shape must match the `health_checks`/`health_issue` variant in
    `frontend/src/queries/schema/schema-signals.ts`. `render_signal` overrides
    call this so the envelope stays consistent across checks.
    """
    return {
        "kind": issue.kind,
        "severity": issue.severity,
        "issue_id": str(issue.id),
        "title": title,
        "summary": summary,
        "link": link,
        "url": f"{settings.SITE_URL}{link}",
        "payload": _bounded_payload_value(issue.payload),
    }


@dataclass(frozen=True)
class HealthCheckRegistration:
    name: str
    kind: str
    owner: JobOwners
    schedule: str | None
    batch_size: int
    max_concurrent: int
    rollout_percentage: float
    not_processed_threshold: float
    dry_run: bool
    active_since_days: int | None
    product: Product | None
    remediation: Remediation | None


def _register_health_check(cls: type[HealthCheck]) -> None:
    existing = HEALTH_CHECKS.get(cls.kind)
    if existing is not None and existing.name != cls.name:
        raise ValueError(f"Health check kind '{cls.kind}' already registered by '{existing.name}'")

    registration = HealthCheckRegistration(
        name=cls.name,
        kind=cls.kind,
        owner=cls.owner,
        schedule=cls.schedule,
        batch_size=cls.policy.batch_size,
        max_concurrent=cls.policy.max_concurrent,
        rollout_percentage=cls.rollout_percentage,
        not_processed_threshold=cls.not_processed_threshold,
        dry_run=cls.dry_run,
        active_since_days=cls.active_since_days,
        product=cls.product,
        remediation=cls.remediation,
    )

    HEALTH_CHECKS[cls.kind] = registration
    _DETECT_FNS[cls.kind] = cls().detect


class HealthCheck:
    name: str
    kind: str
    owner: JobOwners
    product: Product | None = None
    policy: HealthExecutionPolicy = DEFAULT_EXECUTION_POLICY
    schedule: str | None = None
    rollout_percentage: float = 1.0
    not_processed_threshold: float = 0.1
    dry_run: bool = False
    active_since_days: int | None = DEFAULT_ACTIVE_SINCE_DAYS

    # Static, kind-level guidance on how to resolve issues of this kind. Unlike
    # `render_alert` (which describes a *specific* issue), this is the same for
    # every issue of the kind, so it lives as a constant — easy to find and
    # update in one place. Surfaced on the health-issue detail view; the `human`
    # half is also emitted with alerts.
    #
    # Set it to a Remediation with two naturally-indented triple-quoted strings
    # (the Remediation constructor normalises the indentation):
    #   - human: how to fix it in the PostHog UI (no need to repeat the
    #     "what's wrong" — title/summary already cover that).
    #   - agent: how an agent should investigate (which MCP tools to call) and,
    #     where the fix lives in the user's codebase, how to apply it directly
    #     (edit config, bump a dependency, add a route, etc.).
    # Be descriptive — each half doubles as a prompt for its audience.
    remediation: Remediation | None = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "name") or not hasattr(cls, "kind"):
            return
        _register_health_check(cls)

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        raise NotImplementedError

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        """Build the alert content surfaced to HogFunction destinations.

        The default produces a generic title/summary keyed off `kind` and
        `severity` with a link to /health. Concrete checks override this to
        produce a human-readable message that names the affected resource.
        """
        return AlertContent(
            title=cls.name,
            summary=f"{cls.kind} ({issue.severity})",
            link="/health",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        """Build the inbox signal for a newly-firing issue, or None to skip.

        The base default returns None — a check surfaces in the Signals inbox
        only by overriding this and writing its own description / weight / extra.
        Overrides build their own prose rather than reusing `render_alert`: the
        alert phrasing (a destination notification) and the inbox phrasing (a
        reviewer-facing finding) are deliberately separate. Use `_SEVERITY_WEIGHT`
        for the standard severity → weight mapping. The remediation is not set
        here — it comes from the check's static `remediation` constant.
        """
        return None


def health_check_class_for_kind(kind: str) -> type[HealthCheck] | None:
    """Resolve the HealthCheck subclass that produces issues of `kind`.

    The registry only stores instance-bound detect callables, but every
    HealthCheck subclass binds `cls()` so the underlying class is reachable
    via the bound method's `__self__`.
    """
    ensure_registry_loaded()
    fn = _DETECT_FNS.get(kind)
    if fn is None:
        return None
    instance = getattr(fn, "__self__", None)
    return type(instance) if instance is not None else None


def render_alert_for_issue(issue: HealthIssue) -> AlertContent:
    """Render the per-issue envelope (title/summary/link) for an issue.

    Falls back to a generic envelope when the issue's kind has no registered
    check (e.g. a check that was removed after issues were persisted).
    """
    check_cls = health_check_class_for_kind(issue.kind)
    if check_cls is None:
        return AlertContent(title=issue.kind, summary=f"{issue.kind} ({issue.severity})", link="/health")
    return check_cls.render_alert(issue)


def remediation_for_kind(kind: str) -> Remediation | None:
    """Return the static, kind-level remediation guide, or None if there isn't one.

    Read straight from the registry so callers don't need to resolve the check
    class. Unknown kinds (and kinds that never set `remediation`) return None.
    """
    ensure_registry_loaded()
    registration = HEALTH_CHECKS.get(kind)
    if registration is None:
        return None
    return registration.remediation
