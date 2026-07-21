"""Tier-1 ticket incident detection: statistical spike scoring over Postgres ticket counts.

Runs per team from the trends analysis workflow. Evaluates the built-in series
(overall volume, per channel, per priority) plus every enabled alert rule, then
reconciles results against open ``TicketIncident`` rows — the open ACTIVE row is
the dedup/cooldown, so a spike alerts once and auto-resolves once it calms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count, QuerySet
from django.db.models.functions import TruncHour
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.conversations.backend.models import IncidentScope, IncidentStatus, Ticket, TicketAlertRule, TicketIncident
from products.conversations.backend.models.ticket_alert_rule import (
    MAX_ENABLED_RULES_PER_TEAM,
    MAX_RULE_WINDOW_MINUTES,
    MIN_RULE_WINDOW_MINUTES,
    MIN_SPIKE_MULTIPLIER,
)
from products.conversations.backend.temporal.trends.scoring import (
    CALM_RUNS_TO_RESOLVE,
    DEFAULT_MIN_COUNT,
    DEFAULT_MULTIPLIER,
    MAX_INCIDENT_AGE_HOURS,
    SpikeConfig,
    SpikeResult,
    floor_to_hour,
    score_builtin_volume,
    score_window,
)
from products.conversations.backend.ticket_filtering import apply_ticket_filters, rule_filter_params

logger = structlog.get_logger(__name__)

# Window (baseline days + eval window) plus a day of slack for clock alignment.
SERIES_DAYS = 30
SAMPLE_TICKET_LIMIT = 5
SPARKLINE_HOURS = 24
# A dismissed incident suppresses re-fires of the same scope/dimension for this
# long — otherwise a persisting spike would recreate the alert on the next run.
DISMISS_SUPPRESSION_HOURS = 24


@dataclass
class DetectionStats:
    incidents_fired: int = 0
    incidents_resolved: int = 0
    rules_evaluated: int = 0


@dataclass
class Evaluation:
    scope: str
    dimension_value: str
    result: SpikeResult
    rule: TicketAlertRule | None = None
    details: dict[str, Any] = field(default_factory=dict)


def team_spike_config(team: Team) -> SpikeConfig:
    settings_dict = team.conversations_settings or {}
    try:
        multiplier = float(settings_dict.get("trends_spike_multiplier") or DEFAULT_MULTIPLIER)
        min_count = int(settings_dict.get("trends_spike_min_tickets") or DEFAULT_MIN_COUNT)
    except (TypeError, ValueError):
        multiplier, min_count = DEFAULT_MULTIPLIER, DEFAULT_MIN_COUNT
    return SpikeConfig(min_count=max(min_count, 1), multiplier=max(multiplier, MIN_SPIKE_MULTIPLIER))


def _fetch_hourly_buckets(team_id: int, since: datetime) -> list[tuple[datetime, str, str | None, int]]:
    """One aggregate query feeding every built-in series: hourly ticket counts
    sliced by channel and priority over the whole baseline range."""
    rows = (
        Ticket.objects.filter(team_id=team_id, created_at__gte=since)
        .annotate(bucket=TruncHour("created_at", tzinfo=UTC))
        .values("bucket", "channel_source", "priority")
        .annotate(n=Count("id"))
    )
    return [(row["bucket"], row["channel_source"], row["priority"], row["n"]) for row in rows]


def _window_format(window_minutes: int) -> str:
    if window_minutes == 60:
        return "hour"
    if window_minutes % 60 == 0:
        return f"{window_minutes // 60} hours"
    return f"{window_minutes} minutes"


def describe_incident(
    scope: str,
    dimension_value: str,
    result: SpikeResult,
    rule_name: str | None = None,
) -> str:
    """Human title for an incident, shared by the banner, event, and notification."""
    window = _window_format(result.window_minutes)
    ratio = ""
    if result.baseline_median is not None:
        multiple = result.observed / max(result.baseline_median, 1.0)
        if multiple >= 2:
            ratio = f" (~{round(multiple)}× normal)"

    if scope == IncidentScope.RULE:
        return f"Alert rule '{rule_name or 'unknown'}': {result.observed} matching tickets in the last {window}{ratio}"
    if scope == IncidentScope.CHANNEL:
        return f"{result.observed} {dimension_value} tickets in the last {window}{ratio}"
    if scope == IncidentScope.PRIORITY:
        return f"{result.observed} {dimension_value}-priority tickets in the last {window}{ratio}"
    return f"{result.observed} tickets in the last {window}{ratio}"


def _sample_tickets(queryset: QuerySet[Ticket], window_start: datetime) -> list[dict[str, Any]]:
    tickets = queryset.filter(created_at__gte=window_start).order_by("-created_at")[:SAMPLE_TICKET_LIMIT]
    return [{"id": str(ticket.id), "ticket_number": ticket.ticket_number} for ticket in tickets]


def _sparkline(hourly: dict[datetime, int], now: datetime) -> list[int]:
    """Hourly counts for the trailing SPARKLINE_HOURS, oldest first."""
    window_end = floor_to_hour(now)
    return [hourly.get(window_end - timedelta(hours=i), 0) for i in range(SPARKLINE_HOURS, 0, -1)]


def _evaluate_builtin(
    team: Team,
    now: datetime,
    hourly_rows: list[tuple[datetime, str, str | None, int]],
    config: SpikeConfig,
) -> list[Evaluation]:
    overall: dict[datetime, int] = {}
    by_channel: dict[str, dict[datetime, int]] = {}
    by_priority: dict[str, dict[datetime, int]] = {}
    week_cutoff = now - timedelta(days=7)
    week_totals: dict[tuple[str, str], int] = {}

    for bucket, channel, priority, count in hourly_rows:
        overall[bucket] = overall.get(bucket, 0) + count
        channel_series = by_channel.setdefault(channel, {})
        channel_series[bucket] = channel_series.get(bucket, 0) + count
        if priority:
            priority_series = by_priority.setdefault(priority, {})
            priority_series[bucket] = priority_series.get(bucket, 0) + count
        if bucket >= week_cutoff:
            week_totals[("volume", "")] = week_totals.get(("volume", ""), 0) + count
            week_totals[("channel", channel)] = week_totals.get(("channel", channel), 0) + count
            if priority:
                week_totals[("priority", priority)] = week_totals.get(("priority", priority), 0) + count

    evaluations: list[Evaluation] = []

    volume_result = score_builtin_volume(overall, now, week_totals.get(("volume", ""), 0), config)
    window_start = now - timedelta(minutes=volume_result.window_minutes)
    channel_mix = {
        channel: sum(n for bucket, n in series.items() if bucket >= floor_to_hour(window_start))
        for channel, series in by_channel.items()
    }
    evaluations.append(
        Evaluation(
            scope=IncidentScope.VOLUME,
            dimension_value="",
            result=volume_result,
            details={
                "sparkline_hourly": _sparkline(overall, now),
                "channel_mix": {k: v for k, v in channel_mix.items() if v},
                "sample_tickets": _sample_tickets(Ticket.objects.filter(team_id=team.id), window_start)
                if volume_result.fired
                else [],
            },
        )
    )

    for channel, series in sorted(by_channel.items()):
        result = score_builtin_volume(series, now, week_totals.get(("channel", channel), 0), config)
        details: dict[str, Any] = {"sparkline_hourly": _sparkline(series, now)}
        if result.fired:
            details["sample_tickets"] = _sample_tickets(
                Ticket.objects.filter(team_id=team.id, channel_source=channel),
                now - timedelta(minutes=result.window_minutes),
            )
        evaluations.append(
            Evaluation(scope=IncidentScope.CHANNEL, dimension_value=channel, result=result, details=details)
        )

    for priority, series in sorted(by_priority.items()):
        result = score_builtin_volume(series, now, week_totals.get(("priority", priority), 0), config)
        details = {"sparkline_hourly": _sparkline(series, now)}
        if result.fired:
            details["sample_tickets"] = _sample_tickets(
                Ticket.objects.filter(team_id=team.id, priority=priority),
                now - timedelta(minutes=result.window_minutes),
            )
        evaluations.append(
            Evaluation(scope=IncidentScope.PRIORITY, dimension_value=priority, result=result, details=details)
        )

    return evaluations


def _evaluate_rule(team: Team, rule: TicketAlertRule, now: datetime) -> Evaluation:
    params = rule_filter_params(rule.filters or {})
    base_queryset = apply_ticket_filters(Ticket.objects.filter(team_id=team.id), params, team)
    window_minutes = min(max(rule.window_minutes, MIN_RULE_WINDOW_MINUTES), MAX_RULE_WINDOW_MINUTES)
    config = SpikeConfig(
        min_count=max(rule.min_count, 1), multiplier=max(rule.spike_multiplier or 0.0, MIN_SPIKE_MULTIPLIER)
    )
    details: dict[str, Any] = {}

    if rule.spike_multiplier is None:
        # Absolute-only: a single filtered count over the exact window.
        window_start = now - timedelta(minutes=window_minutes)
        observed = base_queryset.filter(created_at__gte=window_start).values("id").distinct().count()
        result = SpikeResult(
            fired=observed >= config.min_count,
            observed=observed,
            window_minutes=window_minutes,
            baseline_median=None,
            zscore=None,
            calm=observed < config.min_count,
        )
    else:
        # Relative: build the rule's own hourly series for a baseline comparison.
        # Whole hours only (rounded up — a 90-minute window evaluates as 2h);
        # Count(distinct) guards against tag-join fan-out from the filters.
        window_hours = min(max(math.ceil(window_minutes / 60), 1), 24)
        series_start = now - timedelta(days=SERIES_DAYS)
        rows = (
            base_queryset.filter(created_at__gte=series_start)
            .annotate(bucket=TruncHour("created_at", tzinfo=UTC))
            .values("bucket")
            .annotate(n=Count("id", distinct=True))
        )
        hourly = {row["bucket"]: row["n"] for row in rows}
        result = score_window(hourly, now, window_hours, config)
        details["sparkline_hourly"] = _sparkline(hourly, now)

    if result.fired:
        details["sample_tickets"] = _sample_tickets(base_queryset, now - timedelta(minutes=result.window_minutes))

    return Evaluation(
        scope=IncidentScope.RULE,
        dimension_value=str(rule.id),
        result=result,
        rule=rule,
        details=details,
    )


def _notify_incident(team: Team, incident: TicketIncident, title: str) -> None:
    """Fire the customer-facing event and the in-app notification. Both are
    best-effort: a delivery hiccup must not fail the detection run."""
    # Deferred: events pulls the HogQL query layer; notifications is another product's facade.
    from products.conversations.backend.events import capture_incident_detected  # noqa: PLC0415
    from products.notifications.backend.facade.api import (  # noqa: PLC0415
        NotificationData,
        NotificationType,
        Priority,
        TargetType,
        create_notification,
    )

    try:
        capture_incident_detected(incident, team, title)
    except Exception:
        capture_exception()
        logger.exception("ticket_trends: incident event capture failed", team_id=team.id, incident_id=str(incident.id))

    settings_dict = team.conversations_settings or {}
    if not settings_dict.get("trends_notifications_enabled", True):
        return
    # Notify the configured recipients (the same user list new-ticket emails use);
    # fall back to the whole team when none are configured.
    recipient_ids = settings_dict.get("notification_recipients") or []
    targets = (
        [(TargetType.USER, str(user_id)) for user_id in recipient_ids]
        if recipient_ids
        else [(TargetType.TEAM, str(team.id))]
    )
    for target_type, target_id in targets:
        try:
            create_notification(
                NotificationData(
                    team_id=team.id,
                    notification_type=NotificationType.ALERT_FIRING,
                    priority=Priority.NORMAL,
                    title=f"Possible support incident: {title}",
                    body="Ticket volume is unusually high. Review the affected tickets in Support.",
                    target_type=target_type,
                    target_id=target_id,
                    source_url="/support/tickets",
                )
            )
        except Exception:
            capture_exception()
            logger.exception(
                "ticket_trends: incident notification failed", team_id=team.id, incident_id=str(incident.id)
            )


def _reconcile(team: Team, evaluations: list[Evaluation], now: datetime, stats: DetectionStats) -> None:
    active_incidents = {
        (incident.scope, incident.dimension_value): incident
        for incident in TicketIncident.objects.for_team(team.id).filter(status=IncidentStatus.ACTIVE)
    }
    recently_dismissed = {
        (incident.scope, incident.dimension_value)
        for incident in TicketIncident.objects.for_team(team.id).filter(
            status=IncidentStatus.DISMISSED,
            updated_at__gte=now - timedelta(hours=DISMISS_SUPPRESSION_HOURS),
        )
    }
    touched: set[tuple[str, str]] = set()
    # Hierarchy: when overall volume fires, its incident carries the channel mix —
    # suppress *new* channel/priority incidents this run so one event doesn't
    # produce three alerts. Existing slice incidents still update below.
    volume_fired = any(
        evaluation.scope == IncidentScope.VOLUME and evaluation.result.fired for evaluation in evaluations
    )

    for evaluation in evaluations:
        key = (evaluation.scope, evaluation.dimension_value)
        touched.add(key)
        incident = active_incidents.get(key)
        result = evaluation.result

        if incident is None:
            if not result.fired or key in recently_dismissed:
                continue
            if volume_fired and evaluation.scope in (IncidentScope.CHANNEL, IncidentScope.PRIORITY):
                continue
            rule_name = evaluation.rule.name if evaluation.rule else None
            title = describe_incident(evaluation.scope, evaluation.dimension_value, result, rule_name)
            try:
                with transaction.atomic():
                    incident = TicketIncident.objects.create(
                        team=team,
                        scope=evaluation.scope,
                        dimension_value=evaluation.dimension_value,
                        rule=evaluation.rule,
                        status=IncidentStatus.ACTIVE,
                        detected_at=now,
                        window_minutes=result.window_minutes,
                        observed_count=result.observed,
                        baseline_value=result.baseline_median,
                        zscore=result.zscore,
                        details={"title": title, **evaluation.details},
                    )
            except IntegrityError:
                # A concurrent run opened the incident first; it owns the alert.
                continue
            if evaluation.rule is not None:
                TicketAlertRule.objects.for_team(team.id).filter(id=evaluation.rule.id).update(last_fired_at=now)
            stats.incidents_fired += 1
            _notify_incident(team, incident, title)
            continue

        if result.fired:
            incident.calm_run_count = 0
            incident.observed_count = result.observed
            incident.baseline_value = result.baseline_median
            incident.zscore = result.zscore
            incident.window_minutes = result.window_minutes
            incident.details = {**incident.details, **evaluation.details}
        elif result.calm:
            incident.calm_run_count += 1
        else:
            incident.calm_run_count = 0

        aged_out = incident.detected_at <= now - timedelta(hours=MAX_INCIDENT_AGE_HOURS)
        if incident.calm_run_count >= CALM_RUNS_TO_RESOLVE or aged_out:
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_at = now
            stats.incidents_resolved += 1
        incident.save()

    # Incidents whose dimension produced no evaluation this run (rule deleted or
    # disabled, slice with no remaining traffic): rule-scoped ones resolve
    # immediately, the rest advance toward calm resolution.
    for key, incident in active_incidents.items():
        if key in touched:
            continue
        if incident.scope == IncidentScope.RULE:
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_at = now
            stats.incidents_resolved += 1
        else:
            incident.calm_run_count += 1
            if incident.calm_run_count >= CALM_RUNS_TO_RESOLVE:
                incident.status = IncidentStatus.RESOLVED
                incident.resolved_at = now
                stats.incidents_resolved += 1
        incident.save()


def run_detection(team_id: int) -> DetectionStats:
    stats = DetectionStats()
    team = Team.objects.get(id=team_id)
    now = timezone.now()
    config = team_spike_config(team)

    # Runs outside request context (Temporal activity), so establish team scope for the
    # fail-closed TicketIncident/TicketAlertRule managers used in reads and the incident write.
    with team_scope(team_id):
        hourly_rows = _fetch_hourly_buckets(team.id, now - timedelta(days=SERIES_DAYS))
        evaluations = _evaluate_builtin(team, now, hourly_rows, config)

        rules = list(
            TicketAlertRule.objects.for_team(team.id)
            .filter(enabled=True)
            .order_by("created_at")[:MAX_ENABLED_RULES_PER_TEAM]
        )
        for rule in rules:
            try:
                evaluations.append(_evaluate_rule(team, rule, now))
                stats.rules_evaluated += 1
            except Exception:
                capture_exception()
                logger.exception("ticket_trends: rule evaluation failed", team_id=team.id, rule_id=str(rule.id))
        if rules:
            TicketAlertRule.objects.for_team(team.id).filter(id__in=[rule.id for rule in rules]).update(
                last_evaluated_at=now
            )

        _reconcile(team, evaluations, now, stats)
    return stats
