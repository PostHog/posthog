"""Activities for evaluation reports workflow."""

import datetime as dt
from zoneinfo import ZoneInfo

import temporalio.activity
from dateutil.rrule import rrulestr
from structlog import get_logger

from posthog.hogql import ast

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.eval_reports.constants import DOGFOOD_TEAM_IDS
from posthog.temporal.llm_analytics.eval_reports.types import (
    CheckCountTriggeredReportsWorkflowInputs,
    DeliverReportInput,
    FetchDueEvalReportsOutput,
    PrepareReportContextInput,
    PrepareReportContextOutput,
    RunEvalReportAgentInput,
    RunEvalReportAgentOutput,
    ScheduleAllEvalReportsWorkflowInputs,
    StoreReportRunInput,
    StoreReportRunOutput,
    UpdateNextDeliveryDateInput,
)

logger = get_logger(__name__)


@temporalio.activity.defn
async def fetch_due_eval_reports_activity(
    inputs: ScheduleAllEvalReportsWorkflowInputs,
) -> FetchDueEvalReportsOutput:
    """Return a list of time-based evaluation report IDs that are due for delivery."""
    now_with_buffer = dt.datetime.now(tz=dt.UTC) + dt.timedelta(minutes=inputs.buffer_minutes)

    @database_sync_to_async(thread_sensitive=False)
    def get_report_ids() -> list[str]:
        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport

        return [
            str(pk)
            for pk in EvaluationReport.objects.filter(
                next_delivery_date__lte=now_with_buffer,
                enabled=True,
                deleted=False,
                team_id__in=DOGFOOD_TEAM_IDS,
            )
            .exclude(frequency=EvaluationReport.Frequency.EVERY_N)
            .values_list("id", flat=True)
        ]

    report_ids = await get_report_ids()
    await logger.ainfo(
        "llma_eval_reports_coordinator_scheduled_poll",
        reports_found=len(report_ids),
    )
    from posthog.temporal.llm_analytics.eval_reports.metrics import record_coordinator_reports_found

    record_coordinator_reports_found(len(report_ids), "scheduled")
    return FetchDueEvalReportsOutput(report_ids=report_ids)


@temporalio.activity.defn
async def fetch_count_triggered_eval_reports_activity(
    inputs: CheckCountTriggeredReportsWorkflowInputs,
) -> FetchDueEvalReportsOutput:
    """Check count-based reports and return those whose eval count exceeds the threshold."""

    @database_sync_to_async(thread_sensitive=False)
    def check_reports() -> tuple[list[str], int, int, int]:
        from posthog.hogql.parser import parse_select
        from posthog.hogql.query import execute_hogql_query

        from posthog.models import Team

        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun

        now = dt.datetime.now(tz=dt.UTC)
        due: list[str] = []
        skipped_cooldown = 0
        skipped_daily_cap = 0

        reports = list(
            EvaluationReport.objects.filter(
                frequency=EvaluationReport.Frequency.EVERY_N,
                enabled=True,
                deleted=False,
                trigger_threshold__isnull=False,
                team_id__in=DOGFOOD_TEAM_IDS,
            ).select_related("evaluation")
        )
        total_checked = len(reports)

        for report in reports:
            # Cooldown: skip if last delivery was too recent
            if report.last_delivered_at:
                cooldown_delta = dt.timedelta(minutes=report.cooldown_minutes)
                if (now - report.last_delivered_at) < cooldown_delta:
                    skipped_cooldown += 1
                    continue

            # Daily cap: skip if too many runs today
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_runs = EvaluationReportRun.objects.filter(
                report=report,
                created_at__gte=today_start,
            ).count()
            if today_runs >= report.daily_run_cap:
                skipped_daily_cap += 1
                continue

            # Count evals since last delivery (or since report creation if first run).
            # starts_at is nullable for count-triggered reports, so fall back to created_at.
            # Pass the datetime directly to ast.Constant — HogQL's printer serializes it
            # as toDateTime64(..., 6, <team_tz>) with correct TZ alignment. A bare string
            # would be coerced in the team's timezone and silently shift the comparison
            # by the team's offset.
            since = report.last_delivered_at or report.starts_at or report.created_at

            team = Team.objects.get(id=report.team_id)
            query = parse_select(
                """
                SELECT count() as total
                FROM events
                WHERE event = '$ai_evaluation'
                    AND properties.$ai_evaluation_id = {evaluation_id}
                    AND timestamp >= {since}
                """,
                placeholders={
                    "evaluation_id": ast.Constant(value=str(report.evaluation_id)),
                    "since": ast.Constant(value=since),
                },
            )
            result = execute_hogql_query(query=query, team=team)
            rows = result.results or []
            count = rows[0][0] if rows else 0

            # The queryset filters trigger_threshold__isnull=False above, so this is
            # always set on rows we iterate — assert for mypy.
            assert report.trigger_threshold is not None
            if count >= report.trigger_threshold:
                due.append(str(report.id))

        return due, total_checked, skipped_cooldown, skipped_daily_cap

    # Heartbeat while the sync loop runs — prevents activity timeout as the
    # number of count-triggered reports grows (each report = 1 HogQL query).
    async with Heartbeater():
        report_ids, total_checked, skipped_cooldown, skipped_daily_cap = await check_reports()
    await logger.ainfo(
        "llma_eval_reports_coordinator_count_triggered_poll",
        reports_found=len(report_ids),
        total_checked=total_checked,
        skipped_cooldown=skipped_cooldown,
        skipped_daily_cap=skipped_daily_cap,
    )
    from posthog.temporal.llm_analytics.eval_reports.metrics import (
        record_coordinator_check_count,
        record_coordinator_reports_found,
    )

    record_coordinator_check_count(total_checked, "count_triggered")
    record_coordinator_reports_found(len(report_ids), "count_triggered")
    return FetchDueEvalReportsOutput(report_ids=report_ids)


def _find_nth_eval_timestamp(
    team_id: int,
    evaluation_id: str,
    n: int,
    before: dt.datetime,
) -> dt.datetime:
    """Find the timestamp of the Nth-most-recent eval result.

    Returns the timestamp so the report window covers exactly the last N evals.
    Falls back to 24h ago if there are fewer than N results.
    """
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.models import Team

    team = Team.objects.get(id=team_id)
    # Pass `before` as a datetime so HogQL serializes it as toDateTime64(..., 6, <team_tz>)
    # instead of a bare string that would be coerced in the team's timezone.
    query = parse_select(
        """
        SELECT min(ts) FROM (
            SELECT timestamp as ts
            FROM events
            WHERE event = '$ai_evaluation'
                AND properties.$ai_evaluation_id = {evaluation_id}
                AND timestamp <= {before}
            ORDER BY timestamp DESC
            LIMIT {limit}
        )
        """,
        placeholders={
            "evaluation_id": ast.Constant(value=evaluation_id),
            "before": ast.Constant(value=before),
            "limit": ast.Constant(value=int(n)),
        },
    )
    result = execute_hogql_query(query=query, team=team)
    rows = result.results or []
    if rows and rows[0][0] is not None:
        ts = rows[0][0]
        if isinstance(ts, dt.datetime):
            if ts.tzinfo is None:
                return ts.replace(tzinfo=dt.UTC)
            return ts
    # Fallback: 24h ago
    return before - dt.timedelta(days=1)


_DEFAULT_PERIOD = dt.timedelta(days=1)


def _period_for_scheduled_report(report, now: dt.datetime) -> dt.timedelta:
    """Return the typical gap between successive RRULE occurrences.

    Used as the "one period" lookback for scheduled reports — e.g. an hourly
    RRULE yields 1h, a weekly RRULE yields 7d. Falls back to 1 day if the rule
    hasn't accumulated enough history yet (fewer than two past occurrences).

    The RRULE is expanded in the report's local timezone so that e.g. "daily
    9am America/New_York" yields a true 23h/25h gap across DST transitions,
    matching the real wall-clock firing cadence rather than a naive UTC delta.
    """
    if not report.rrule or not report.starts_at:
        return _DEFAULT_PERIOD
    try:
        tz = ZoneInfo(report.timezone_name or "UTC")
        starts_local = report.starts_at.astimezone(tz).replace(tzinfo=None)
        rule = rrulestr(report.rrule, dtstart=starts_local, ignoretz=True)
    except (ValueError, TypeError):
        return _DEFAULT_PERIOD
    now_local = now.astimezone(tz).replace(tzinfo=None)
    prev = rule.before(now_local, inc=False)
    if prev is None:
        return _DEFAULT_PERIOD
    prev_prev = rule.before(prev, inc=False)
    if prev_prev is None:
        return _DEFAULT_PERIOD
    # Reattach the target tz and normalize to UTC so the returned delta reflects
    # the real wall-clock gap (23/24/25h around DST), not the naive-local delta.
    prev_utc = prev.replace(tzinfo=tz).astimezone(dt.UTC)
    prev_prev_utc = prev_prev.replace(tzinfo=tz).astimezone(dt.UTC)
    return prev_utc - prev_prev_utc


@temporalio.activity.defn
async def prepare_report_context_activity(
    inputs: PrepareReportContextInput,
) -> PrepareReportContextOutput:
    """Load evaluation from Postgres and calculate time windows."""

    @database_sync_to_async(thread_sensitive=False)
    def prepare() -> PrepareReportContextOutput:
        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport

        report = EvaluationReport.objects.select_related("evaluation").get(id=inputs.report_id)
        evaluation = report.evaluation
        now = dt.datetime.now(tz=dt.UTC)

        period_end = now

        if inputs.manual:
            # Manual "Generate now": always look back one full period so the
            # user gets something meaningful regardless of last delivery.
            if report.is_count_triggered:
                # For count-triggered reports, sample the most recent N evals so
                # "Generate now" always produces something useful even if the
                # threshold hasn't been crossed yet.
                period_start = _find_nth_eval_timestamp(
                    team_id=report.team_id,
                    evaluation_id=str(evaluation.id),
                    n=report.trigger_threshold or 100,
                    before=now,
                )
            else:
                period_start = now - _period_for_scheduled_report(report, now)
        elif report.last_delivered_at:
            period_start = report.last_delivered_at
        else:
            # First run: look back one typical period (count-triggered reports
            # fall back to the report's anchor — starts_at if present, else its
            # creation time — since they don't have a natural cadence).
            if report.is_count_triggered:
                period_start = report.starts_at or report.created_at
            else:
                period_start = now - _period_for_scheduled_report(report, now)

        # Previous period for comparison (same duration, shifted back)
        period_duration = period_end - period_start
        previous_period_start = period_start - period_duration

        guidance = report.report_prompt_guidance or ""

        return PrepareReportContextOutput(
            report_id=str(report.id),
            team_id=report.team_id,
            evaluation_id=str(evaluation.id),
            evaluation_name=evaluation.name,
            evaluation_description=evaluation.description or "",
            evaluation_prompt=evaluation.evaluation_config.get("prompt", ""),
            evaluation_type=evaluation.evaluation_type,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            previous_period_start=previous_period_start.isoformat(),
            report_prompt_guidance=guidance,
        )

    return await prepare()


@temporalio.activity.defn
async def run_eval_report_agent_activity(
    inputs: RunEvalReportAgentInput,
) -> RunEvalReportAgentOutput:
    """Run the LLM report agent."""
    async with Heartbeater():
        await logger.ainfo(
            "llma_eval_reports_agent_started",
            report_id=inputs.report_id,
            team_id=inputs.team_id,
            evaluation_id=inputs.evaluation_id,
        )

        @database_sync_to_async(thread_sensitive=False)
        def run_agent():
            from posthog.temporal.llm_analytics.eval_reports.report_agent import run_eval_report_agent

            return run_eval_report_agent(
                team_id=inputs.team_id,
                evaluation_id=inputs.evaluation_id,
                evaluation_name=inputs.evaluation_name,
                evaluation_description=inputs.evaluation_description,
                evaluation_prompt=inputs.evaluation_prompt,
                evaluation_type=inputs.evaluation_type,
                period_start=inputs.period_start,
                period_end=inputs.period_end,
                previous_period_start=inputs.previous_period_start,
                report_prompt_guidance=inputs.report_prompt_guidance,
            )

        content = await run_agent()

        return RunEvalReportAgentOutput(
            report_id=inputs.report_id,
            content=content.to_dict(),
            period_start=inputs.period_start,
            period_end=inputs.period_end,
        )


@temporalio.activity.defn
async def store_report_run_activity(
    inputs: StoreReportRunInput,
) -> StoreReportRunOutput:
    """Save the generated report as an EvaluationReportRun and emit a $ai_evaluation_report event."""

    @database_sync_to_async(thread_sensitive=False)
    def store() -> str:
        import uuid

        from posthog.models.event.util import create_event
        from posthog.models.team import Team

        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReportRun

        # Mirror content.metrics into the legacy `metadata` JSONField so existing
        # consumers that read from it (e.g. the UI's run preview before Commit 2's
        # frontend refresh) still work.
        content = inputs.content or {}
        metrics = content.get("metrics", {}) or {}

        run = EvaluationReportRun.objects.create(
            report_id=inputs.report_id,
            content=content,
            metadata=metrics,
            period_start=inputs.period_start,
            period_end=inputs.period_end,
        )

        # Emit $ai_evaluation_report event to ClickHouse
        team = Team.objects.get(id=inputs.team_id)

        # Collect citations from structured content (v2), not from per-section lists
        citations = content.get("citations", []) or []
        all_referenced_ids = [c.get("generation_id", "") for c in citations if c.get("generation_id")]

        properties: dict = {
            "$ai_evaluation_id": inputs.evaluation_id,
            "$ai_evaluation_report_id": str(run.report_id),
            "$ai_evaluation_report_run_id": str(run.id),
            "$ai_report_title": content.get("title", ""),
            "$ai_report_period_start": inputs.period_start,
            "$ai_report_period_end": inputs.period_end,
            # Metrics for querying/alerting (flattened from content.metrics)
            "$ai_report_total_runs": metrics.get("total_runs", 0),
            "$ai_report_pass_count": metrics.get("pass_count", 0),
            "$ai_report_fail_count": metrics.get("fail_count", 0),
            "$ai_report_na_count": metrics.get("na_count", 0),
            "$ai_report_pass_rate": metrics.get("pass_rate", 0.0),
            "$ai_report_previous_pass_rate": metrics.get("previous_pass_rate"),
            "$ai_report_previous_total_runs": metrics.get("previous_total_runs"),
            # Structured content + citations for downstream consumption
            "$ai_report_content": content,
            "$ai_report_citations": citations,
            "$ai_report_referenced_generation_ids": all_referenced_ids,
            "$ai_report_section_count": len(content.get("sections", [])),
        }

        create_event(
            event_uuid=uuid.uuid4(),
            event="$ai_evaluation_report",
            team=team,
            distinct_id=f"eval_report_{inputs.team_id}",
            properties=properties,
        )

        return str(run.id)

    run_id = await store()
    return StoreReportRunOutput(report_run_id=run_id)


@temporalio.activity.defn
async def deliver_report_activity(
    inputs: DeliverReportInput,
) -> None:
    """Deliver the report via configured delivery targets (email/Slack)."""
    async with Heartbeater():
        await logger.ainfo(
            "llma_eval_reports_delivery_started",
            report_id=inputs.report_id,
            report_run_id=inputs.report_run_id,
        )

        @database_sync_to_async(thread_sensitive=False)
        def deliver():
            from posthog.temporal.llm_analytics.eval_reports.delivery import deliver_report

            deliver_report(
                report_id=inputs.report_id,
                report_run_id=inputs.report_run_id,
            )

        await deliver()


@temporalio.activity.defn
async def update_next_delivery_date_activity(
    inputs: UpdateNextDeliveryDateInput,
) -> None:
    """Update the report's next_delivery_date and last_delivered_at.

    last_delivered_at is set to the report's period_end (captured at the start of
    this run) rather than the current wall-clock time. This guarantees that the
    next run's period_start picks up exactly where this run's period_end left off,
    so any time spent generating/delivering does not create a coverage gap.
    """

    @database_sync_to_async(thread_sensitive=False)
    def update():
        import datetime as dt_mod

        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport

        report = EvaluationReport.objects.get(id=inputs.report_id)
        report.last_delivered_at = dt_mod.datetime.fromisoformat(inputs.period_end)
        report.set_next_delivery_date()
        report.save(update_fields=["last_delivered_at", "next_delivery_date"])

    await update()
