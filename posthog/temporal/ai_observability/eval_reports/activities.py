"""Activities for evaluation reports workflow."""

import datetime as dt
from collections import defaultdict
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import temporalio.activity
from dateutil.rrule import rrulestr
from structlog import get_logger

from posthog.hogql import ast

from posthog.clickhouse.client.connection import Workload
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.eval_reports.constants import COUNT_TRIGGER_QUERY_WIDTH
from posthog.temporal.ai_observability.eval_reports.output_types import get_outcome_definition
from posthog.temporal.ai_observability.eval_reports.targets import (
    GENERATION_TARGET,
    resolve_evaluation_target,
    target_event_predicate,
)
from posthog.temporal.ai_observability.eval_reports.types import (
    CheckCountTriggeredEvalReportInput,
    CheckCountTriggeredEvalReportOutput,
    CheckCountTriggeredEvalReportsBatchInput,
    CheckCountTriggeredEvalReportsBatchOutput,
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
from posthog.temporal.common.heartbeat import Heartbeater

if TYPE_CHECKING:
    from posthog.models import Team

    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

logger = get_logger(__name__)


@temporalio.activity.defn
async def fetch_due_eval_reports_activity(
    inputs: ScheduleAllEvalReportsWorkflowInputs,
) -> FetchDueEvalReportsOutput:
    """Return a list of time-based evaluation report IDs that are due for delivery."""
    now_with_buffer = dt.datetime.now(tz=dt.UTC) + dt.timedelta(minutes=inputs.buffer_minutes)

    @database_sync_to_async(thread_sensitive=False)
    def get_report_ids() -> list[str]:
        from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

        return [
            str(pk)
            for pk in EvaluationReport.objects.deliverable()
            .filter(
                next_delivery_date__lte=now_with_buffer,
            )
            .exclude(frequency=EvaluationReport.Frequency.EVERY_N)
            .values_list("id", flat=True)
        ]

    report_ids = await get_report_ids()
    await logger.ainfo(
        "llma_eval_reports_coordinator_scheduled_poll",
        reports_found=len(report_ids),
    )
    from posthog.temporal.ai_observability.eval_reports.metrics import record_coordinator_reports_found

    record_coordinator_reports_found(len(report_ids), "scheduled")
    return FetchDueEvalReportsOutput(report_ids=report_ids)


@temporalio.activity.defn
async def fetch_count_triggered_eval_report_candidates_activity(
    inputs: CheckCountTriggeredReportsWorkflowInputs,
) -> FetchDueEvalReportsOutput:
    """Return count-triggered report IDs that need an independent count check, grouped
    one team per group so each check activity runs a single shared count query."""

    @database_sync_to_async(thread_sensitive=False)
    def get_report_id_groups() -> list[list[str]]:
        return _fetch_count_triggered_eval_report_candidate_groups()

    report_id_groups = await get_report_id_groups()
    report_ids = [report_id for group in report_id_groups for report_id in group]
    await logger.ainfo(
        "llma_eval_reports_coordinator_count_triggered_candidates_poll",
        total_checked=len(report_ids),
    )
    from posthog.temporal.ai_observability.eval_reports.metrics import record_coordinator_check_count

    record_coordinator_check_count(len(report_ids), "count_triggered")
    return FetchDueEvalReportsOutput(report_ids=report_ids, report_id_groups=report_id_groups)


@temporalio.activity.defn
async def check_count_triggered_eval_report_activity(
    inputs: CheckCountTriggeredEvalReportInput,
) -> CheckCountTriggeredEvalReportOutput:
    """Check one count-triggered report against its threshold.

    Superseded by check_count_triggered_eval_reports_activity (batched). Kept registered
    so coordinator workflows started before the batched path was deployed can finish.
    """

    @database_sync_to_async(thread_sensitive=False)
    def check_report() -> CheckCountTriggeredEvalReportOutput:
        return _check_count_triggered_eval_report_sync(inputs.report_id)

    return await check_report()


@temporalio.activity.defn
async def check_count_triggered_eval_reports_activity(
    inputs: CheckCountTriggeredEvalReportsBatchInput,
) -> CheckCountTriggeredEvalReportsBatchOutput:
    """Check a batch of count-triggered reports, sharing one ClickHouse query per team."""

    @database_sync_to_async(thread_sensitive=False)
    def check_reports() -> list[CheckCountTriggeredEvalReportOutput]:
        return _check_count_triggered_eval_reports_batch(inputs.report_ids)

    results = await check_reports()
    return CheckCountTriggeredEvalReportsBatchOutput(results=results)


def _fetch_count_triggered_eval_report_candidate_groups() -> list[list[str]]:
    """Return candidate report ids grouped one team per group, each group at most
    COUNT_TRIGGER_QUERY_WIDTH wide, so one check activity runs exactly one ClickHouse
    count query under its own timeout and retry policy."""
    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

    ids_by_team: dict[int, list[str]] = defaultdict(list)
    for pk, team_id in (
        EvaluationReport.objects.deliverable()
        .filter(
            frequency=EvaluationReport.Frequency.EVERY_N,
            trigger_threshold__isnull=False,
        )
        .order_by("team_id", "id")
        .values_list("id", "team_id")
    ):
        ids_by_team[team_id].append(str(pk))
    return [chunk for ids in ids_by_team.values() for chunk in _chunk(ids, COUNT_TRIGGER_QUERY_WIDTH)]


def _load_count_triggered_report(report_id: str) -> "EvaluationReport | None":
    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

    return (
        EvaluationReport.objects.deliverable()
        .filter(
            id=report_id,
            frequency=EvaluationReport.Frequency.EVERY_N,
            trigger_threshold__isnull=False,
        )
        .select_related("evaluation", "team")
        .first()
    )


def _count_triggered_pg_gate(
    report: "EvaluationReport",
    now: dt.datetime,
) -> tuple[str | None, dt.datetime | None]:
    """Postgres-only eligibility checks shared by the single and batched count paths.

    Returns (skipped_reason, since). When skipped_reason is None the report is eligible
    for a count check and `since` is the lower bound of its count window.
    """
    from products.ai_observability.backend.models.evaluation_reports import EvaluationReportRun

    if report.last_delivered_at:
        cooldown_delta = dt.timedelta(minutes=report.cooldown_minutes)
        if (now - report.last_delivered_at) < cooldown_delta:
            return "cooldown", None

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_runs = EvaluationReportRun.objects.filter(
        report=report,
        created_at__gte=today_start,
    ).count()
    if today_runs >= report.daily_run_cap:
        return "daily_cap", None

    since = report.last_delivered_at or report.starts_at or report.created_at
    return None, since


def _check_count_triggered_eval_report_sync(
    report_id: str,
    now: dt.datetime | None = None,
) -> CheckCountTriggeredEvalReportOutput:
    report = _load_count_triggered_report(report_id)
    if report is None:
        return CheckCountTriggeredEvalReportOutput(report_id=report_id, due=False, skipped_reason="not_deliverable")

    now = now or dt.datetime.now(tz=dt.UTC)
    skipped_reason, since = _count_triggered_pg_gate(report, now)
    if skipped_reason is not None:
        return CheckCountTriggeredEvalReportOutput(report_id=report_id, due=False, skipped_reason=skipped_reason)

    assert since is not None
    count = _count_eval_results_for_report(report, since)

    assert report.trigger_threshold is not None
    return CheckCountTriggeredEvalReportOutput(report_id=report_id, due=count >= report.trigger_threshold)


def _chunk(items: list, size: int) -> list[list]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _check_count_triggered_eval_reports_batch(
    report_ids: list[str],
    now: dt.datetime | None = None,
) -> list[CheckCountTriggeredEvalReportOutput]:
    """Check a group of count-triggered reports, sharing one ClickHouse count query per team.

    The input is normally one team's reports (the fetch activity groups candidates that way),
    but multi-team input is handled by grouping — one query per team-chunk. The Postgres
    gating (deliverability, cooldown, daily cap) and the `count >= threshold` decision are
    identical to the single-report path — only the count query is shared.

    A ClickHouse failure propagates and fails the whole activity, which normally spans just
    one team's chunk — Temporal retries it under the activity's retry policy.
    """
    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

    now = now or dt.datetime.now(tz=dt.UTC)

    reports = {
        str(report.id): report
        for report in EvaluationReport.objects.deliverable()
        .filter(
            id__in=report_ids,
            frequency=EvaluationReport.Frequency.EVERY_N,
            trigger_threshold__isnull=False,
        )
        .select_related("evaluation", "team")
    }

    outputs: dict[str, CheckCountTriggeredEvalReportOutput] = {}
    # team_id -> list of (report_id, report, since) for reports that passed the Postgres gate
    survivors: dict[int, list[tuple[str, EvaluationReport, dt.datetime]]] = defaultdict(list)

    for report_id in report_ids:
        report = reports.get(report_id)
        if report is None:
            outputs[report_id] = CheckCountTriggeredEvalReportOutput(
                report_id=report_id, due=False, skipped_reason="not_deliverable"
            )
            continue
        skipped_reason, since = _count_triggered_pg_gate(report, now)
        if skipped_reason is not None:
            outputs[report_id] = CheckCountTriggeredEvalReportOutput(
                report_id=report_id, due=False, skipped_reason=skipped_reason
            )
            continue
        assert since is not None
        survivors[report.team_id].append((report_id, report, since))

    for entries in survivors.values():
        team = entries[0][1].team
        # Cap the per-query width so a team with many reports doesn't build one giant query.
        for chunk in _chunk(entries, COUNT_TRIGGER_QUERY_WIDTH):
            counts = _count_eval_results_for_reports(
                team,
                [
                    (
                        report_id,
                        str(report.evaluation_id),
                        since,
                        get_outcome_definition(report.evaluation.output_type).event_predicate,
                    )
                    for report_id, report, since in chunk
                ],
            )
            for report_id, report, _since in chunk:
                assert report.trigger_threshold is not None
                outputs[report_id] = CheckCountTriggeredEvalReportOutput(
                    report_id=report_id, due=counts.get(report_id, 0) >= report.trigger_threshold
                )

    # Preserve input order so the workflow's aggregation and logging stay deterministic.
    return [outputs[report_id] for report_id in report_ids]


def _count_eval_results_for_report(report: "EvaluationReport", since: dt.datetime) -> int:
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    # Pass the datetime directly to ast.Constant. HogQL's printer serializes it
    # as toDateTime64(..., 6, <team_tz>) with correct TZ alignment. A bare string
    # would be coerced in the team's timezone and silently shift the comparison
    # by the team's offset.
    outcome_definition = get_outcome_definition(report.evaluation.output_type)
    evaluation_target_predicate = target_event_predicate(report.evaluation.target)
    # nosemgrep: hogql-fstring-audit (the predicate comes from fixed internal output-type definitions)
    query = parse_select(
        f"""
        SELECT count() as total
        FROM events
        WHERE event = '$ai_evaluation'
            AND properties.$ai_evaluation_id = {{evaluation_id}}
            AND {outcome_definition.event_predicate}
            AND {evaluation_target_predicate}
            AND timestamp >= {{since}}
        """,
        placeholders={
            "evaluation_id": ast.Constant(value=str(report.evaluation_id)),
            "since": ast.Constant(value=since),
        },
    )
    # These count checks run every 5 minutes across all count-triggered reports, so keep them
    # off the online cluster that serves user-facing queries — route to the offline replica.
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.ENRICHMENT, team_id=report.team_id):
        result = execute_hogql_query(query=query, team=report.team, workload=Workload.OFFLINE)
    rows = result.results or []
    if not rows:
        return 0
    return int(rows[0][0] or 0)


def _count_eval_results_for_reports(
    team: "Team",
    entries: list[tuple[str, str, dt.datetime, str]],
) -> dict[str, int]:
    """Count `$ai_evaluation` events for many reports in a single ClickHouse query.

    Each entry is (key, evaluation_id, since, event_predicate). We emit one `countIf`
    column per entry, each carrying the exact per-report predicate (evaluation_id +
    output-type `event_predicate` + `timestamp >= since`), so every count equals what the
    single-report query would return. The shared WHERE only narrows the scan (its `IN` set
    and `min(since)` never exclude a row any countIf would have counted). Returns {key: count}.
    """
    from posthog.hogql.parser import parse_expr, parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    if not entries:
        return {}

    # evaluation_id and since go in as ast.Constant placeholders (no interpolation to audit);
    # `since` stays a datetime so HogQL prints toDateTime64(..., 6, <team_tz>) — a bare string
    # would shift by the team's offset. event_predicate is a trusted internal output-type
    # definition (never user input), interpolated to match the single-report query exactly.
    # Columns are read positionally below, so no aliases are needed.
    select_columns: list[ast.Expr] = [
        # nosemgrep: hogql-fstring-audit (the predicate comes from fixed internal output-type definitions)
        parse_expr(
            f"countIf(properties.$ai_evaluation_id = {{evaluation_id}} AND {event_predicate} AND timestamp >= {{since}})",
            placeholders={
                "evaluation_id": ast.Constant(value=evaluation_id),
                "since": ast.Constant(value=since),
            },
        )
        for _key, evaluation_id, since, event_predicate in entries
    ]

    unique_evaluation_ids = list(dict.fromkeys(evaluation_id for _key, evaluation_id, _since, _pred in entries))
    query = parse_select(
        "SELECT 1 FROM events WHERE event = '$ai_evaluation' "
        "AND properties.$ai_evaluation_id IN {evaluation_ids} AND timestamp >= {min_since}",
        placeholders={
            "evaluation_ids": ast.Tuple(exprs=[ast.Constant(value=e) for e in unique_evaluation_ids]),
            "min_since": ast.Constant(value=min(since for _key, _evaluation_id, since, _pred in entries)),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    # Replace the placeholder projection with the per-entry count columns.
    query.select = select_columns

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.ENRICHMENT, team_id=team.pk):
        result = execute_hogql_query(query=query, team=team, workload=Workload.OFFLINE)

    rows = result.results or []
    if not rows:
        return {key: 0 for key, _evaluation_id, _since, _pred in entries}
    row = rows[0]
    return {entries[index][0]: int(row[index] or 0) for index in range(len(entries))}


def _find_nth_eval_timestamp(
    team_id: int,
    evaluation_id: str,
    n: int,
    before: dt.datetime,
    output_type: str = "boolean",
    evaluation_target: str = "generation",
) -> dt.datetime:
    """Find the timestamp of the Nth-most-recent eval result.

    Returns the timestamp so the report window covers exactly the last N evals.
    Falls back to 24h ago if there are fewer than N results.
    """
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.clickhouse.query_tagging import Feature, Product, tags_context
    from posthog.models import Team

    team = Team.objects.get(id=team_id)
    # Pass `before` as a datetime so HogQL serializes it as toDateTime64(..., 6, <team_tz>)
    # instead of a bare string that would be coerced in the team's timezone.
    outcome_definition = get_outcome_definition(output_type)
    evaluation_target_predicate = target_event_predicate(evaluation_target)
    # nosemgrep: hogql-fstring-audit (the predicate comes from fixed internal output-type definitions)
    query = parse_select(
        f"""
        SELECT min(ts) FROM (
            SELECT timestamp as ts
            FROM events
            WHERE event = '$ai_evaluation'
                AND properties.$ai_evaluation_id = {{evaluation_id}}
                AND {outcome_definition.event_predicate}
                AND {evaluation_target_predicate}
                AND timestamp <= {{before}}
            ORDER BY timestamp DESC
            LIMIT {{limit}}
        )
        """,
        placeholders={
            "evaluation_id": ast.Constant(value=evaluation_id),
            "before": ast.Constant(value=before),
            "limit": ast.Constant(value=int(n)),
        },
    )
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.ENRICHMENT, team_id=team.pk):
        result = execute_hogql_query(query=query, team=team, workload=Workload.OFFLINE)
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
        from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

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
                    output_type=evaluation.output_type,
                    evaluation_target=evaluation.target,
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
            output_type=evaluation.output_type,
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
            from posthog.temporal.ai_observability.eval_reports.report_agent import run_eval_report_agent

            evaluation_target = _load_evaluation_target(inputs.team_id, inputs.evaluation_id)
            return (
                run_eval_report_agent(
                    team_id=inputs.team_id,
                    evaluation_id=inputs.evaluation_id,
                    evaluation_name=inputs.evaluation_name,
                    evaluation_description=inputs.evaluation_description,
                    evaluation_prompt=inputs.evaluation_prompt,
                    evaluation_type=inputs.evaluation_type,
                    evaluation_target=evaluation_target,
                    output_type=inputs.output_type,
                    period_start=inputs.period_start,
                    period_end=inputs.period_end,
                    previous_period_start=inputs.previous_period_start,
                    report_prompt_guidance=inputs.report_prompt_guidance,
                ),
                evaluation_target,
            )

        content, evaluation_target = await run_agent()
        content.evaluation_target = evaluation_target

        return RunEvalReportAgentOutput(
            report_id=inputs.report_id,
            content=content.to_dict(),
            period_start=inputs.period_start,
            period_end=inputs.period_end,
        )


def _load_evaluation_target(team_id: int, evaluation_id: str) -> str:
    from products.ai_observability.backend.models.evaluations import (  # noqa: PLC0415 -- keep Django model loading inside activity execution
        Evaluation,
    )

    return Evaluation.objects.values_list("target", flat=True).get(id=evaluation_id, team_id=team_id)


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
        from posthog.temporal.ai_observability.eval_reports.report_agent.schema import (  # noqa: PLC0415 -- keeps report agent dependencies off the activity import path
            EvalReportMetrics,
            normalize_report_content_payload,
        )

        from products.ai_observability.backend.models.evaluation_reports import EvaluationReportRun

        # Mirror content.metrics into the legacy `metadata` JSONField for consumers that still read it.
        content = normalize_report_content_payload(inputs.content or {})
        evaluation_target = resolve_evaluation_target(content.get("evaluation_target", GENERATION_TARGET))
        metrics = content.get("metrics", {}) or {}
        parsed_metrics = EvalReportMetrics.from_dict(metrics)

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
        all_referenced_trace_ids = [c.get("trace_id", "") for c in citations if c.get("trace_id")]

        properties: dict = {
            "$ai_evaluation_id": inputs.evaluation_id,
            "$ai_evaluation_report_id": str(run.report_id),
            "$ai_evaluation_report_run_id": str(run.id),
            "$ai_report_title": content.get("title", ""),
            "$ai_report_period_start": inputs.period_start,
            "$ai_report_period_end": inputs.period_end,
            "$ai_report_output_type": parsed_metrics.output_type,
            "$ai_report_evaluation_target": evaluation_target,
            "$ai_report_result_counts": parsed_metrics.result_counts,
            "$ai_report_result_rates": parsed_metrics.result_rates,
            "$ai_report_previous_result_counts": parsed_metrics.previous_result_counts,
            "$ai_report_previous_result_rates": parsed_metrics.previous_result_rates,
            "$ai_report_total_runs": parsed_metrics.total_runs,
            "$ai_report_previous_total_runs": parsed_metrics.previous_total_runs,
            # Structured content + citations for downstream consumption
            "$ai_report_content": content,
            "$ai_report_citations": citations,
            "$ai_report_referenced_generation_ids": all_referenced_ids,
            "$ai_report_referenced_trace_ids": all_referenced_trace_ids,
            "$ai_report_section_count": len(content.get("sections", [])),
        }
        if parsed_metrics.output_type == "boolean":
            # Preserve the original flat properties for existing boolean-report consumers.
            properties.update(
                {
                    "$ai_report_pass_count": parsed_metrics.result_counts["pass"],
                    "$ai_report_fail_count": parsed_metrics.result_counts["fail"],
                    "$ai_report_na_count": parsed_metrics.result_counts["na"],
                    "$ai_report_pass_rate": parsed_metrics.pass_rate,
                    "$ai_report_previous_pass_rate": parsed_metrics.previous_pass_rate,
                }
            )

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
            from posthog.temporal.ai_observability.eval_reports.delivery import deliver_report

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

        from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

        report = EvaluationReport.objects.get(id=inputs.report_id)
        report.last_delivered_at = dt_mod.datetime.fromisoformat(inputs.period_end)
        report.set_next_delivery_date()
        report.save(update_fields=["last_delivered_at", "next_delivery_date"])

    await update()
