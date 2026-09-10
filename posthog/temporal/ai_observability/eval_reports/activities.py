"""Activities for evaluation reports workflow."""

import math
import time
import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import batched, zip_longest
from typing import TYPE_CHECKING, Any, NamedTuple
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from django.db.models import Q, QuerySet

import temporalio.activity
from dateutil.rrule import rrulestr
from structlog import get_logger

from posthog.hogql import ast

from posthog.clickhouse.client.connection import Workload
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models.temporal_scheduler import TemporalSchedulerState
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.eval_reports.constants import (
    COUNT_TRIGGER_QUERY_MAX_EXECUTION_TIME_SECONDS,
    COUNT_TRIGGER_QUERY_MIN_EXECUTION_TIME_SECONDS,
    COUNT_TRIGGER_QUERY_MIN_SPLIT_RANGE,
    COUNT_TRIGGER_QUERY_OVERSHOOT_FACTOR,
    COUNT_TRIGGER_QUERY_RETRY_MAX_EXECUTION_TIME_SECONDS,
    COUNT_TRIGGER_QUERY_TOTAL_BUDGET_SECONDS,
    COUNT_TRIGGER_QUERY_WIDTH,
)
from posthog.temporal.ai_observability.eval_reports.output_types import get_outcome_definition
from posthog.temporal.ai_observability.eval_reports.targets import (
    GENERATION_TARGET,
    resolve_evaluation_target,
    target_event_predicate,
)
from posthog.temporal.ai_observability.eval_reports.types import (
    AckEvalReportCursorsInput,
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
from posthog.temporal.scheduler.metrics import DEFAULT_SCHEDULER_METRICS, record_scheduler_metrics_safely
from posthog.temporal.scheduler.payload import select_items_within_temporal_payload

if TYPE_CHECKING:
    from posthog.models import Team

    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

logger = get_logger(__name__)

_SCHEDULED_EVAL_REPORTS_SCHEDULER = "eval_reports_scheduled"
_COUNT_TRIGGERED_EVAL_REPORTS_SCHEDULER = "eval_reports_count_triggered"
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_MAX_DISCOVERY_REFILL_ROUNDS = 12

# Mirrors REPORTABLE_OUTPUT_TYPES_BY_TARGET, which owns the reportability contract. The
# products import is deferred to activity call time, so these module-level SQL constants
# cannot read the owner directly; TestReportabilityContract pins the two together.
_REPORTABLE_TARGET_OUTPUT_TYPES: dict[str, tuple[str, ...]] = {
    "generation": ("boolean", "sentiment"),
    "trace": ("boolean",),
    "session": ("boolean",),
}

_REPORTABLE_TARGET_PREDICATES = "\n        OR ".join(
    f"(evaluation.target = '{target}' AND evaluation.output_type = '{output_type}')"
    for target, output_types in _REPORTABLE_TARGET_OUTPUT_TYPES.items()
    for output_type in output_types
)

_REPORTABLE_EVALUATION_SQL = f"""
    evaluation.enabled = TRUE
    AND evaluation.deleted = FALSE
    AND (
        {_REPORTABLE_TARGET_PREDICATES}
    )
"""

_SCHEDULED_REPORT_CANDIDATE_SQL = f"""
    WITH selected_teams AS (
        SELECT team_id, item_cursor, team_order
        FROM unnest(%s::bigint[], %s::uuid[]) WITH ORDINALITY
            AS selected(team_id, item_cursor, team_order)
    ),
    bounded_candidates AS (
        SELECT
            selected_teams.team_id,
            selected_teams.team_order,
            candidate.id,
            candidate.next_delivery_date,
            candidate.team_rank
        FROM selected_teams
        CROSS JOIN LATERAL (
            SELECT
                report.id,
                report.next_delivery_date,
                ROW_NUMBER() OVER (
                    -- The item cursor stores an id, so ranking must use the same id order.
                    -- Mixing next_delivery_date into this order can leave an oldest-due
                    -- report at the front forever after the cursor wraps past the largest id.
                    ORDER BY (report.id <= selected_teams.item_cursor), report.id
                ) AS team_rank
            FROM llm_analytics_evaluationreport AS report
            INNER JOIN llm_analytics_evaluation AS evaluation ON evaluation.id = report.evaluation_id
            WHERE report.team_id = selected_teams.team_id
              AND report.enabled = TRUE
              AND report.deleted = FALSE
              AND report.frequency = 'scheduled'
              AND report.next_delivery_date <= %s
              AND {_REPORTABLE_EVALUATION_SQL}
            ORDER BY team_rank
            LIMIT %s
            OFFSET %s
        ) AS candidate
    )
    SELECT id, team_id, next_delivery_date
    FROM bounded_candidates
    ORDER BY team_rank, team_order, next_delivery_date, id
    LIMIT %s
"""

_COUNT_TRIGGERED_REPORT_CANDIDATE_SQL = f"""
    WITH selected_teams AS (
        SELECT team_id, item_cursor, team_order
        FROM unnest(%s::bigint[], %s::uuid[]) WITH ORDINALITY
            AS selected(team_id, item_cursor, team_order)
    ),
    bounded_candidates AS (
        SELECT
            selected_teams.team_id,
            selected_teams.team_order,
            candidate.id,
            candidate.team_rank
        FROM selected_teams
        CROSS JOIN LATERAL (
            SELECT
                report.id,
                -- Ranked here, in the same cursor-relative order the rows are taken in, so
                -- the wrapped-around ids keep their place at the front of the team. Ranking
                -- the page again by plain id would sort them back to last and drop them at
                -- the outer LIMIT, which strands the tail of the ring on every poll.
                ROW_NUMBER() OVER (
                    ORDER BY (report.id <= selected_teams.item_cursor), report.id
                ) AS team_rank
            FROM llm_analytics_evaluationreport AS report
            INNER JOIN llm_analytics_evaluation AS evaluation ON evaluation.id = report.evaluation_id
            WHERE report.team_id = selected_teams.team_id
              AND report.enabled = TRUE
              AND report.deleted = FALSE
              AND report.frequency = 'every_n'
              AND report.trigger_threshold IS NOT NULL
              AND {_REPORTABLE_EVALUATION_SQL}
            ORDER BY team_rank
            LIMIT %s
            OFFSET %s
        ) AS candidate
    )
    SELECT id, team_id, NULL::timestamptz AS occurrence_at
    FROM bounded_candidates
    ORDER BY team_rank, team_order, id
    LIMIT %s
"""


class _EvalReportCandidatePage(NamedTuple):
    rows: list[tuple[str, int]]
    items_lower_bound: int
    oldest_due_at: dt.datetime | None
    team_cursor: str
    occurrence_keys: dict[str, str]


@temporalio.activity.defn
async def fetch_due_eval_reports_activity(
    inputs: ScheduleAllEvalReportsWorkflowInputs,
) -> FetchDueEvalReportsOutput:
    """Return a list of time-based evaluation report IDs that are due for delivery."""
    from posthog.temporal.ai_observability.eval_reports.types import MAX_SCHEDULED_EVAL_REPORTS_PER_RUN

    _validate_discovery_inputs(inputs.max_reports_per_run, MAX_SCHEDULED_EVAL_REPORTS_PER_RUN, inputs.region)
    if not 0 <= inputs.buffer_minutes <= 60:
        raise ValueError("buffer_minutes must be between 0 and 60")
    now_with_buffer = dt.datetime.now(tz=dt.UTC) + dt.timedelta(minutes=inputs.buffer_minutes)

    @database_sync_to_async(thread_sensitive=False)
    def get_report_candidates() -> _EvalReportCandidatePage:
        from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

        due_reports = (
            EvaluationReport.objects.deliverable()
            .filter(
                frequency=EvaluationReport.Frequency.SCHEDULED,
                next_delivery_date__lte=now_with_buffer,
            )
            .order_by()
        )
        oldest_due_at = (
            due_reports.order_by("next_delivery_date", "id").values_list("next_delivery_date", flat=True).first()
        )
        return _fetch_eval_report_candidate_page(
            due_reports,
            scheduler=_SCHEDULED_EVAL_REPORTS_SCHEDULER,
            region=inputs.region,
            max_reports_per_run=inputs.max_reports_per_run,
            candidate_sql=_SCHEDULED_REPORT_CANDIDATE_SQL,
            candidate_sql_params=[now_with_buffer],
            oldest_due_at=oldest_due_at,
            rotate_item_cursor=True,
        )

    candidates = await get_report_candidates()
    selection = await select_items_within_temporal_payload(
        candidates.rows,
        build_payload=lambda rows: FetchDueEvalReportsOutput(
            report_ids=[report_id for report_id, _team_id in rows],
            report_occurrence_keys={
                report_id: candidates.occurrence_keys[report_id]
                for report_id, _team_id in rows
                if report_id in candidates.occurrence_keys
            },
            due_items_lower_bound=candidates.items_lower_bound,
            oldest_due_at_iso=candidates.oldest_due_at.isoformat() if candidates.oldest_due_at else None,
            cursor_before=candidates.team_cursor,
        ),
        max_items=inputs.max_reports_per_run,
    )
    report_ids = [report_id for report_id, _team_id in selection.items]
    limited_by = _effective_limit(selection.limited_by, candidates.items_lower_bound, len(report_ids))
    oldest_age_seconds = _oldest_age_seconds(candidates.oldest_due_at)
    record_scheduler_metrics_safely(
        lambda: DEFAULT_SCHEDULER_METRICS.observe_payload(
            _SCHEDULED_EVAL_REPORTS_SCHEDULER,
            inputs.region,
            "discovery",
            selection.encoded_size_bytes,
        )
    )
    record_scheduler_metrics_safely(
        lambda: DEFAULT_SCHEDULER_METRICS.set_backlog(
            _SCHEDULED_EVAL_REPORTS_SCHEDULER,
            inputs.region,
            candidates.items_lower_bound,
            oldest_age_seconds,
        )
    )
    await logger.ainfo(
        "llma_eval_reports_coordinator_scheduled_poll",
        reports_found=len(report_ids),
        due_items_lower_bound=candidates.items_lower_bound,
        oldest_age_seconds=oldest_age_seconds,
        payload_bytes=selection.encoded_size_bytes,
        limited_by=limited_by,
        cursor_before=candidates.team_cursor,
        region=inputs.region,
    )
    from posthog.temporal.ai_observability.eval_reports.metrics import record_coordinator_reports_found

    record_coordinator_reports_found(len(report_ids), "scheduled")
    return FetchDueEvalReportsOutput(
        report_ids=report_ids,
        report_occurrence_keys={
            report_id: candidates.occurrence_keys[report_id]
            for report_id in report_ids
            if report_id in candidates.occurrence_keys
        },
        due_items_lower_bound=candidates.items_lower_bound,
        oldest_due_at_iso=candidates.oldest_due_at.isoformat() if candidates.oldest_due_at else None,
        payload_bytes=selection.encoded_size_bytes,
        limited_by=limited_by,
        cursor_before=candidates.team_cursor,
    )


@temporalio.activity.defn
async def fetch_count_triggered_eval_report_candidates_activity(
    inputs: CheckCountTriggeredReportsWorkflowInputs,
) -> FetchDueEvalReportsOutput:
    """Return count-triggered report IDs that need an independent count check, grouped
    one team per group so each check activity runs a single shared count query."""

    from posthog.temporal.ai_observability.eval_reports.types import MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN

    _validate_discovery_inputs(inputs.max_reports_per_run, MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN, inputs.region)

    @database_sync_to_async(thread_sensitive=False)
    def get_report_candidates() -> _EvalReportCandidatePage:
        from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

        reports = (
            EvaluationReport.objects.deliverable()
            .filter(
                frequency=EvaluationReport.Frequency.EVERY_N,
                trigger_threshold__isnull=False,
            )
            .order_by()
        )
        return _fetch_eval_report_candidate_page(
            reports,
            scheduler=_COUNT_TRIGGERED_EVAL_REPORTS_SCHEDULER,
            region=inputs.region,
            max_reports_per_run=inputs.max_reports_per_run,
            candidate_sql=_COUNT_TRIGGERED_REPORT_CANDIDATE_SQL,
            rotate_item_cursor=True,
        )

    candidates = await get_report_candidates()
    selection = await select_items_within_temporal_payload(
        candidates.rows,
        build_payload=lambda rows: _count_triggered_payload(
            rows,
            candidates.items_lower_bound,
            candidates.team_cursor,
        ),
        max_items=inputs.max_reports_per_run,
    )
    report_id_groups = _group_count_triggered_report_rows(selection.items)
    report_ids = [report_id for report_id, _team_id in selection.items]
    limited_by = _effective_limit(selection.limited_by, candidates.items_lower_bound, len(report_ids))
    record_scheduler_metrics_safely(
        lambda: DEFAULT_SCHEDULER_METRICS.observe_payload(
            _COUNT_TRIGGERED_EVAL_REPORTS_SCHEDULER,
            inputs.region,
            "discovery",
            selection.encoded_size_bytes,
        )
    )
    await logger.ainfo(
        "llma_eval_reports_coordinator_count_triggered_candidates_poll",
        total_checked=len(report_ids),
        candidates_lower_bound=candidates.items_lower_bound,
        payload_bytes=selection.encoded_size_bytes,
        limited_by=limited_by,
        region=inputs.region,
    )
    from posthog.temporal.ai_observability.eval_reports.metrics import (
        record_coordinator_candidate_inventory,
        record_coordinator_check_count,
    )

    record_coordinator_check_count(len(report_ids), "count_triggered")
    record_scheduler_metrics_safely(
        lambda: record_coordinator_candidate_inventory(
            candidates.items_lower_bound,
            "count_triggered",
            inputs.region,
            saturated=candidates.items_lower_bound > len(report_ids),
        )
    )
    return FetchDueEvalReportsOutput(
        report_ids=report_ids,
        report_id_groups=report_id_groups,
        team_by_report_id=dict(selection.items),
        due_items_lower_bound=candidates.items_lower_bound,
        payload_bytes=selection.encoded_size_bytes,
        limited_by=limited_by,
        cursor_before=candidates.team_cursor,
    )


def _validate_discovery_inputs(max_reports_per_run: int, hard_maximum: int, region: str) -> None:
    if not 1 <= max_reports_per_run <= hard_maximum:
        raise ValueError(f"max_reports_per_run must be between 1 and {hard_maximum}")
    if not region.strip() or len(region) > 32:
        raise ValueError("region must contain between 1 and 32 characters")


def _effective_limit(payload_limit: str, items_lower_bound: int, selected_count: int) -> str:
    if payload_limit == "none" and items_lower_bound > selected_count:
        return "item_limit"
    return payload_limit


def _oldest_age_seconds(oldest_due_at: dt.datetime | None) -> float:
    if oldest_due_at is None:
        return 0.0
    return max((dt.datetime.now(tz=dt.UTC) - oldest_due_at).total_seconds(), 0.0)


def _group_count_triggered_report_rows(rows: Sequence[tuple[str, int]]) -> list[list[str]]:
    ids_by_team: dict[int, list[str]] = defaultdict(list)
    for report_id, team_id in rows:
        ids_by_team[team_id].append(report_id)
    chunks_by_team = [
        [list(chunk) for chunk in batched(ids, COUNT_TRIGGER_QUERY_WIDTH, strict=False)] for ids in ids_by_team.values()
    ]
    # Interleaved by chunk rank, so every team's first chunk lands in an early check window.
    # The workflow takes fixed-size windows off this list in order, so emitting one team's
    # chunks back to back would let a team with several chunks hold the early windows and
    # push the rest of the page behind it.
    return [chunk for rank in zip_longest(*chunks_by_team) for chunk in rank if chunk is not None]


def _count_triggered_payload(
    rows: Sequence[tuple[str, int]],
    items_lower_bound: int,
    cursor_before: str,
) -> FetchDueEvalReportsOutput:
    return FetchDueEvalReportsOutput(
        report_ids=[report_id for report_id, _team_id in rows],
        report_id_groups=_group_count_triggered_report_rows(rows),
        team_by_report_id=dict(rows),
        due_items_lower_bound=items_lower_bound,
        cursor_before=cursor_before,
    )


def _fetch_eval_report_candidate_page(
    reports: QuerySet["EvaluationReport"],
    *,
    scheduler: str,
    region: str,
    max_reports_per_run: int,
    candidate_sql: str,
    candidate_sql_params: list[object] | None = None,
    oldest_due_at: dt.datetime | None = None,
    rotate_item_cursor: bool = False,
) -> _EvalReportCandidatePage:
    """Select a bounded, tenant-fair page without ranking an unbounded report set."""

    with transaction.atomic():
        state, _ = TemporalSchedulerState.objects.get_or_create(scheduler=scheduler, region=region)
        state = TemporalSchedulerState.objects.select_for_update().get(pk=state.pk)
        team_discovery_cursor = state.discovery_cursor
        try:
            team_cursor = int(team_discovery_cursor or 0)
        except ValueError:
            team_cursor = 0

        teams_after_cursor = list(
            reports.filter(team_id__gt=team_cursor)
            .order_by("team_id")
            .values_list("team_id", flat=True)
            .distinct()[: max_reports_per_run + 1]
        )
        selected_team_ids = teams_after_cursor[:max_reports_per_run]
        deferred_teams = len(teams_after_cursor) > max_reports_per_run
        remaining_team_slots = max_reports_per_run - len(selected_team_ids)
        if remaining_team_slots:
            teams_before_cursor = list(
                reports.filter(team_id__lte=team_cursor)
                .order_by("team_id")
                .values_list("team_id", flat=True)
                .distinct()[: remaining_team_slots + 1]
            )
            selected_team_ids.extend(teams_before_cursor[:remaining_team_slots])
            deferred_teams = deferred_teams or len(teams_before_cursor) > remaining_team_slots
        elif team_cursor:
            deferred_teams = deferred_teams or reports.filter(team_id__lte=team_cursor).exists()

        if not selected_team_ids:
            return _EvalReportCandidatePage([], 0, oldest_due_at, team_discovery_cursor, {})

        candidate_limit = max_reports_per_run + 1
        candidates_per_team = math.ceil(candidate_limit / len(selected_team_ids))
        item_cursors = (
            _load_eval_report_item_cursors(scheduler, region, selected_team_ids) if rotate_item_cursor else {}
        )
        bounded_rows: list[tuple[str, int]] = []
        occurrence_keys: dict[str, str] = {}
        teams_to_fetch = selected_team_ids
        candidates_to_skip_per_team = 0
        for _round in range(_MAX_DISCOVERY_REFILL_ROUNDS):
            remaining_candidate_slots = candidate_limit - len(bounded_rows)
            query_params: list[Any] = [
                teams_to_fetch,
                *([item_cursors[team_id] for team_id in teams_to_fetch] if rotate_item_cursor else []),
                *(candidate_sql_params or []),
                candidates_per_team,
                candidates_to_skip_per_team,
                remaining_candidate_slots,
            ]
            with connection.cursor() as cursor:
                cursor.execute(candidate_sql, query_params)
                raw_rows = cursor.fetchall()
                round_rows = [(str(report_id), int(team_id)) for report_id, team_id, _occurrence_at in raw_rows]
                bounded_rows.extend(round_rows)
                occurrence_keys.update(
                    {
                        str(report_id): occurrence_at.isoformat()
                        for report_id, _team_id, occurrence_at in raw_rows
                        if occurrence_at is not None
                    }
                )

            if len(bounded_rows) >= candidate_limit or not round_rows:
                break
            rows_per_team = Counter(team_id for _report_id, team_id in round_rows)
            teams_to_fetch = [team_id for team_id in teams_to_fetch if rows_per_team[team_id] == candidates_per_team]
            if not teams_to_fetch:
                break
            candidates_to_skip_per_team += candidates_per_team
            candidates_per_team = max(1, math.ceil((candidate_limit - len(bounded_rows)) / len(teams_to_fetch)))

    deferred_candidates = len(bounded_rows) > max_reports_per_run
    selected_rows = bounded_rows[:max_reports_per_run]
    items_lower_bound = len(selected_rows) + int(deferred_teams or deferred_candidates)
    return _EvalReportCandidatePage(
        selected_rows,
        items_lower_bound,
        oldest_due_at,
        team_discovery_cursor,
        {
            report_id: occurrence_keys[report_id]
            for report_id, _team_id in selected_rows
            if report_id in occurrence_keys
        },
    )


def _item_cursor_scheduler(scheduler: str, team_id: int) -> str:
    return f"{scheduler}_items:{team_id}"


def _load_eval_report_item_cursor_states(
    scheduler: str,
    region: str,
    team_ids: Sequence[int],
) -> dict[int, TemporalSchedulerState]:
    scheduler_by_team = {team_id: _item_cursor_scheduler(scheduler, team_id) for team_id in team_ids}
    states_by_scheduler = {
        state.scheduler: state
        for state in TemporalSchedulerState.objects.select_for_update().filter(
            scheduler__in=scheduler_by_team.values(),
            region=region,
        )
    }
    missing_schedulers = set(scheduler_by_team.values()) - states_by_scheduler.keys()
    if missing_schedulers:
        TemporalSchedulerState.objects.bulk_create(
            [TemporalSchedulerState(scheduler=item_scheduler, region=region) for item_scheduler in missing_schedulers],
            ignore_conflicts=True,
        )
        states_by_scheduler.update(
            {
                state.scheduler: state
                for state in TemporalSchedulerState.objects.select_for_update().filter(
                    scheduler__in=missing_schedulers,
                    region=region,
                )
            }
        )
    return {team_id: states_by_scheduler[item_scheduler] for team_id, item_scheduler in scheduler_by_team.items()}


def _load_eval_report_item_cursors(
    scheduler: str,
    region: str,
    team_ids: Sequence[int],
) -> dict[int, str]:
    states = _load_eval_report_item_cursor_states(scheduler, region, team_ids)
    cursors: dict[int, str] = {}
    for team_id, state in states.items():
        try:
            cursors[team_id] = str(UUID(state.discovery_cursor)) if state.discovery_cursor else _ZERO_UUID
        except ValueError:
            cursors[team_id] = _ZERO_UUID
    return cursors


def _eval_report_cursor_ack_already_applied(
    state: TemporalSchedulerState,
    next_team_cursor: str,
    item_states: dict[int, TemporalSchedulerState],
    last_report_id_by_team: dict[int, str],
) -> bool:
    if state.discovery_cursor != next_team_cursor:
        return False
    return not item_states or all(
        item_states[team_id].discovery_cursor == report_id for team_id, report_id in last_report_id_by_team.items()
    )


def _advance_eval_report_cursors(
    page: _EvalReportCandidatePage,
    selected_rows: Sequence[tuple[str, int]],
    *,
    scheduler: str,
    region: str,
    rotate_item_cursor: bool,
) -> bool:
    if not selected_rows:
        return False

    next_team_cursor = str(selected_rows[-1][1])
    last_report_id_by_team = {team_id: report_id for report_id, team_id in selected_rows}
    with transaction.atomic():
        state = TemporalSchedulerState.objects.select_for_update().get(scheduler=scheduler, region=region)
        item_states: dict[int, TemporalSchedulerState] = {}
        if rotate_item_cursor:
            item_states = _load_eval_report_item_cursor_states(
                scheduler,
                region,
                list(last_report_id_by_team),
            )

        if state.discovery_cursor != page.team_cursor:
            # The activity may have committed and then lost its reply. Treat the exact
            # post-ack state as success so Temporal retries are idempotent, while a genuinely
            # different cursor still exposes concurrent or stale work.
            return _eval_report_cursor_ack_already_applied(
                state,
                next_team_cursor,
                item_states,
                last_report_id_by_team,
            )

        if state.discovery_cursor != next_team_cursor:
            state.discovery_cursor = next_team_cursor
            state.save(update_fields=["discovery_cursor", "updated_at"])
        if item_states:
            updated_at = dt.datetime.now(tz=dt.UTC)
            changed_item_states: list[TemporalSchedulerState] = []
            for team_id, report_id in last_report_id_by_team.items():
                item_state = item_states[team_id]
                if item_state.discovery_cursor != report_id:
                    item_state.discovery_cursor = report_id
                    item_state.updated_at = updated_at
                    changed_item_states.append(item_state)
            if changed_item_states:
                TemporalSchedulerState.objects.bulk_update(
                    changed_item_states,
                    ["discovery_cursor", "updated_at"],
                )

    return True


@temporalio.activity.defn
async def ack_eval_report_cursors_activity(inputs: AckEvalReportCursorsInput) -> bool:
    """Advance discovery only after the coordinator has durably received and processed a page."""

    if inputs.trigger_type == "scheduled":
        scheduler = _SCHEDULED_EVAL_REPORTS_SCHEDULER
        rotate_item_cursor = True
    elif inputs.trigger_type == "count_triggered":
        scheduler = _COUNT_TRIGGERED_EVAL_REPORTS_SCHEDULER
        rotate_item_cursor = True
    else:
        raise ValueError("unsupported evaluation report trigger_type")

    @database_sync_to_async(thread_sensitive=False)
    def ack() -> bool:
        from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

        team_by_report_id = {
            str(report_id): int(team_id)
            for report_id, team_id in EvaluationReport.objects.filter(id__in=inputs.report_ids).values_list(
                "id", "team_id"
            )
        }
        selected_rows = [
            (report_id, team_by_report_id[report_id])
            for report_id in inputs.report_ids
            if report_id in team_by_report_id
        ]
        return _advance_eval_report_cursors(
            _EvalReportCandidatePage([], 0, None, inputs.cursor_before, {}),
            selected_rows,
            scheduler=scheduler,
            region=inputs.region,
            rotate_item_cursor=rotate_item_cursor,
        )

    return await ack()


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
    from posthog.temporal.ai_observability.eval_reports.types import MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN

    from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

    ids_by_team: dict[int, list[str]] = defaultdict(list)
    for pk, team_id in (
        EvaluationReport.objects.deliverable()
        .filter(
            frequency=EvaluationReport.Frequency.EVERY_N,
            trigger_threshold__isnull=False,
        )
        .order_by("team_id", "id")
        .values_list("id", "team_id")[:MAX_COUNT_TRIGGERED_EVAL_REPORTS_PER_RUN]
    ):
        ids_by_team[team_id].append(str(pk))
    return _group_count_triggered_report_rows(
        [(report_id, team_id) for team_id, report_ids in ids_by_team.items() for report_id in report_ids]
    )


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

    cooldown_anchor = report.last_attempted_at or report.last_delivered_at
    if cooldown_anchor:
        cooldown_delta = dt.timedelta(minutes=report.cooldown_minutes)
        if (now - cooldown_anchor) < cooldown_delta:
            return "cooldown", None

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_runs = EvaluationReportRun.objects.filter(
        Q(content__generation_status__isnull=True) | ~Q(content__generation_status="metrics_unavailable"),
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
    occurrence_anchor = report.last_attempted_at or report.last_delivered_at or report.starts_at or report.created_at
    return CheckCountTriggeredEvalReportOutput(
        report_id=report_id,
        due=count >= report.trigger_threshold,
        occurrence_key=occurrence_anchor.isoformat(),
    )


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

    deadline = time.monotonic() + COUNT_TRIGGER_QUERY_TOTAL_BUDGET_SECONDS
    for entries in survivors.values():
        team = entries[0][1].team
        # Sort by `since` before capping the per-query width, so entries sharing a chunk
        # have a comparable window — one stale report no longer sets the scan's lower
        # bound for every other report queued alongside it.
        entries.sort(key=lambda entry: entry[2])
        for chunk in batched(entries, COUNT_TRIGGER_QUERY_WIDTH, strict=False):
            counts = _count_eval_results_for_reports_with_split_retry(
                team,
                [
                    _CountEntry(
                        key=report_id,
                        evaluation_id=str(report.evaluation_id),
                        since=since,
                        event_predicate=get_outcome_definition(report.evaluation.output_type).event_predicate,
                        target_predicate=target_event_predicate(report.evaluation.target),
                    )
                    for report_id, report, since in chunk
                ],
                until=now,
                deadline=deadline,
            )
            for report_id, report, _since in chunk:
                assert report.trigger_threshold is not None
                occurrence_anchor = (
                    report.last_attempted_at or report.last_delivered_at or report.starts_at or report.created_at
                )
                outputs[report_id] = CheckCountTriggeredEvalReportOutput(
                    report_id=report_id,
                    due=counts.get(report_id, 0) >= report.trigger_threshold,
                    occurrence_key=occurrence_anchor.isoformat(),
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


class _CountEntry(NamedTuple):
    key: str
    evaluation_id: str
    since: dt.datetime
    event_predicate: str
    target_predicate: str


def _count_eval_results_for_reports(
    team: "Team",
    entries: list[_CountEntry],
    since: dt.datetime,
    until: dt.datetime,
    max_execution_time: int,
) -> dict[str, int]:
    """Count `$ai_evaluation` events for many reports over one time range, in a single
    ClickHouse query.

    We emit one `countIf` column per entry, each carrying the exact per-report predicate
    (evaluation_id + output-type `event_predicate` + `target_predicate` + `timestamp >=
    entry.since`), so a call covering every entry's own window returns what the single-report
    query would. The shared WHERE narrows the scan to `since`..`until` and to the entries'
    evaluation ids. Callers that pass a range narrower than an entry's own window get that
    range's share of the count, and must sum the shares to get the entry's total.
    Returns {key: count}.
    """
    from posthog.hogql.constants import HogQLGlobalSettings
    from posthog.hogql.parser import parse_expr, parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.clickhouse.query_tagging import Feature, Product, tags_context

    if not entries:
        return {}

    # evaluation_id and since go in as ast.Constant placeholders (no interpolation to audit);
    # `since` stays a datetime so HogQL prints toDateTime64(..., 6, <team_tz>) — a bare string
    # would shift by the team's offset. The predicates are trusted internal output-type and
    # target definitions (never user input), interpolated to match the single-report query
    # exactly. Columns are read positionally below, so no aliases are needed.
    select_columns: list[ast.Expr] = [
        # nosemgrep: hogql-fstring-audit (the predicates come from fixed internal definitions)
        parse_expr(
            f"countIf(properties.$ai_evaluation_id = {{evaluation_id}}"
            f" AND {entry.event_predicate} AND {entry.target_predicate} AND timestamp >= {{since}})",
            placeholders={
                "evaluation_id": ast.Constant(value=entry.evaluation_id),
                "since": ast.Constant(value=entry.since),
            },
        )
        for entry in entries
    ]

    unique_evaluation_ids = list(dict.fromkeys(entry.evaluation_id for entry in entries))
    query = parse_select(
        "SELECT 1 FROM events WHERE event = '$ai_evaluation' "
        "AND properties.$ai_evaluation_id IN {evaluation_ids} "
        "AND timestamp >= {since} AND timestamp <= {until}",
        placeholders={
            "evaluation_ids": ast.Tuple(exprs=[ast.Constant(value=e) for e in unique_evaluation_ids]),
            "since": ast.Constant(value=since),
            "until": ast.Constant(value=until),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    # Replace the placeholder projection with the per-entry count columns.
    query.select = select_columns

    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.ENRICHMENT, team_id=team.pk):
        result = execute_hogql_query(
            query=query,
            team=team,
            workload=Workload.OFFLINE,
            # "throw", not the profile default: the split retry needs the timeout to raise. A
            # partial count reads as below threshold and silently keeps the report from firing.
            settings=HogQLGlobalSettings(max_execution_time=max_execution_time, timeout_overflow_mode="throw"),
        )

    rows = result.results or []
    if not rows:
        return {entry.key: 0 for entry in entries}
    row = rows[0]
    return {entries[index].key: int(row[index] or 0) for index in range(len(entries))}


def _count_eval_results_for_reports_with_split_retry(
    team: "Team",
    entries: list[_CountEntry],
    until: dt.datetime,
    since: dt.datetime | None = None,
    deadline: float | None = None,
    max_execution_time: int = COUNT_TRIGGER_QUERY_MAX_EXECUTION_TIME_SECONDS,
) -> dict[str, int]:
    """Run the batched count query, halving the time range and retrying over each half if
    ClickHouse can't finish it inside its own execution-time budget.

    A `ClickHouseQueryTimeOut` means the rows in `since`..`until` don't fit the budget, so
    replaying the identical query would just time out again. Halving the range halves the
    rows each attempt reads, and the two halves sum to the same per-entry counts. Splitting
    the countIf columns instead would leave both halves reading almost the same rows, because
    the columns share one scan and the width barely moves its cost.

    Every attempt draws on one shared wall-clock budget (`deadline`, in `time.monotonic()`
    seconds), capping its own execution time by what remains, so the whole split tree
    concludes before the activity's own timeout. ClickHouse can overrun its execution limit,
    so an attempt only claims a limit it can afford to overshoot by
    COUNT_TRIGGER_QUERY_OVERSHOOT_FACTOR. Once the remainder can't fund a meaningful query,
    the timeout surfaces and the activity fails cleanly instead of being killed mid-split by
    Temporal.
    """
    if since is None:
        since = min(entry.since for entry in entries)
    if deadline is None:
        deadline = time.monotonic() + COUNT_TRIGGER_QUERY_TOTAL_BUDGET_SECONDS
    affordable_execution_time = int((deadline - time.monotonic()) / COUNT_TRIGGER_QUERY_OVERSHOOT_FACTOR)
    budget = min(max_execution_time, affordable_execution_time)
    if budget < COUNT_TRIGGER_QUERY_MIN_EXECUTION_TIME_SECONDS:
        raise ClickHouseQueryTimeOut("Count query budget exhausted before the split could finish.")
    try:
        return _count_eval_results_for_reports(team, entries, since=since, until=until, max_execution_time=budget)
    except ClickHouseQueryTimeOut:
        if (until - since) <= COUNT_TRIGGER_QUERY_MIN_SPLIT_RANGE:
            raise
        midpoint = since + (until - since) / 2
        counts = _count_eval_results_for_reports_with_split_retry(
            team,
            entries,
            since=since,
            until=midpoint,
            deadline=deadline,
            max_execution_time=COUNT_TRIGGER_QUERY_RETRY_MAX_EXECUTION_TIME_SECONDS,
        )
        # The events table stores timestamps as DateTime64(6), so one microsecond past the
        # midpoint is the next representable instant and the halves cannot overlap.
        later_half = _count_eval_results_for_reports_with_split_retry(
            team,
            entries,
            since=midpoint + dt.timedelta(microseconds=1),
            until=until,
            deadline=deadline,
            max_execution_time=COUNT_TRIGGER_QUERY_RETRY_MAX_EXECUTION_TIME_SECONDS,
        )
        for key, count in later_half.items():
            counts[key] = counts.get(key, 0) + count
        return counts


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
            true_is_failure=bool(evaluation.output_config.get("true_is_failure")),
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
                    inputs,
                    evaluation_target=evaluation_target,
                    detector_evaluation_ids=_load_detector_evaluation_ids(inputs.team_id),
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
            generation_status=content.generation_status.value,
        )


def _load_evaluation_target(team_id: int, evaluation_id: str) -> str:
    from products.ai_observability.backend.models.evaluations import (  # noqa: PLC0415 -- keep Django model loading inside activity execution
        Evaluation,
    )

    return Evaluation.objects.values_list("target", flat=True).get(id=evaluation_id, team_id=team_id)


def _load_detector_evaluation_ids(team_id: int) -> list[str]:
    """The generation detail tool lists every evaluation on a generation, not just this report's,
    so it needs each one's polarity to label it. Read here rather than in the context activity,
    which would carry the whole team's list through two Temporal payloads to reach this one."""
    from products.ai_observability.backend.models.evaluations import (  # noqa: PLC0415 -- keep Django model loading inside activity execution
        Evaluation,
    )

    return [
        str(evaluation_id)
        for evaluation_id in Evaluation.objects.filter(
            team_id=team_id, output_type="boolean", output_config__true_is_failure=True
        ).values_list("id", flat=True)
    ]


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
            EvalReportGenerationStatus,
            EvalReportMetrics,
            normalize_report_content_payload,
        )

        from products.ai_observability.backend.models.evaluation_reports import EvaluationReportRun

        # Mirror content.metrics into the legacy `metadata` JSONField for consumers that still read it.
        content = normalize_report_content_payload(inputs.content or {})
        evaluation_target = resolve_evaluation_target(content.get("evaluation_target", GENERATION_TARGET))
        generation_status = EvalReportGenerationStatus(content["generation_status"])
        metrics = content.get("metrics")
        parsed_metrics = EvalReportMetrics.from_dict(metrics) if isinstance(metrics, dict) else None

        run = EvaluationReportRun.objects.create(
            report_id=inputs.report_id,
            content=content,
            metadata=metrics or {},
            period_start=inputs.period_start,
            period_end=inputs.period_end,
        )

        # Emit $ai_evaluation_report event to ClickHouse
        team = Team.objects.get(id=inputs.team_id)

        # Collect citations from structured content (v2), not from per-section lists
        citations = content.get("citations", []) or []
        all_referenced_ids = [c.get("generation_id", "") for c in citations if c.get("generation_id")]
        all_referenced_trace_ids = [c.get("trace_id", "") for c in citations if c.get("trace_id")]
        all_referenced_session_ids = [c.get("session_id", "") for c in citations if c.get("session_id")]

        properties: dict = {
            "$ai_evaluation_id": inputs.evaluation_id,
            "$ai_evaluation_report_id": str(run.report_id),
            "$ai_evaluation_report_run_id": str(run.id),
            "$ai_report_title": content.get("title", ""),
            "$ai_report_period_start": inputs.period_start,
            "$ai_report_period_end": inputs.period_end,
            "$ai_report_evaluation_target": evaluation_target,
            "$ai_report_generation_status": generation_status.value,
            # Structured content + citations for downstream consumption
            "$ai_report_content": content,
            "$ai_report_citations": citations,
            "$ai_report_referenced_generation_ids": all_referenced_ids,
            "$ai_report_referenced_trace_ids": all_referenced_trace_ids,
            "$ai_report_referenced_session_ids": all_referenced_session_ids,
            "$ai_report_section_count": len(content.get("sections", [])),
        }
        if parsed_metrics is not None:
            properties.update(
                {
                    "$ai_report_output_type": parsed_metrics.output_type,
                    "$ai_report_result_counts": parsed_metrics.result_counts,
                    "$ai_report_result_rates": parsed_metrics.result_rates,
                    "$ai_report_previous_result_counts": parsed_metrics.previous_result_counts,
                    "$ai_report_previous_result_rates": parsed_metrics.previous_result_rates,
                    "$ai_report_total_runs": parsed_metrics.total_runs,
                    "$ai_report_previous_total_runs": parsed_metrics.previous_total_runs,
                }
            )
        if parsed_metrics is not None and parsed_metrics.output_type == "boolean":
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


def _update_next_delivery_date(inputs: UpdateNextDeliveryDateInput) -> None:
    """Persist automatic-run timing without creating gaps in the report data cursor.

    `period_end` is captured when report context is prepared. It anchors both the
    attempt and successful cursor so time spent generating and delivering cannot
    leave uncovered data between consecutive reports.

    `advance_data_cursor=None` preserves the behavior of activity inputs recorded
    before attempt and delivery updates were split.
    """
    from products.ai_observability.backend.models.evaluation_reports import (  # noqa: PLC0415 -- keeps product model loading inside activity execution
        EvaluationReport,
    )

    report = EvaluationReport.objects.get(id=inputs.report_id)
    period_end = dt.datetime.fromisoformat(inputs.period_end)
    advance_data_cursor = (
        inputs.generation_status == "completed" if inputs.advance_data_cursor is None else inputs.advance_data_cursor
    )
    update_fields: list[str] = []
    if inputs.record_attempt:
        report.last_attempted_at = period_end
        report.set_next_delivery_date()
        update_fields.extend(["next_delivery_date", "last_attempted_at"])
    if advance_data_cursor:
        report.last_delivered_at = period_end
        update_fields.append("last_delivered_at")
    report.save(update_fields=update_fields)


@temporalio.activity.defn
async def update_next_delivery_date_activity(
    inputs: UpdateNextDeliveryDateInput,
) -> None:
    @database_sync_to_async(thread_sensitive=False)
    def update() -> None:
        _update_next_delivery_date(inputs)

    await update()
