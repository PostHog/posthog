from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from itertools import batched
from typing import IO

from django.utils.timezone import now

from posthog.schema import HogQLPropertyFilter

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.exports.backend.facade.api import (
    EXPORT_WORKFLOW_TIMEOUT,
    ExportedAsset,
    create_export_asset_async,
    get_export_asset,
    is_export_failure_final,
)

from ..logic.evaluations.evaluation_metas import load_evaluation_meta, load_evaluation_metas
from ..logic.evaluations.overview import evaluation_result, group_by_evaluation, overview_totals, pass_rate_overview
from ..logic.evaluations.overview_queries import load_bucket_counts, load_category_counts
from ..logic.evaluations.pass_filters import build_evaluation_pass_filters, build_pass_rules
from ..logic.evaluations.period import (
    InvalidPeriodError as InvalidPeriodError,
    PeriodBounds,
    overview_period,
)
from ..logic.evaluations.runs import RunOutcome, load_runs
from ..logic.evaluations.score_distribution import load_score_distribution, score_buckets
from ..logic.traces.evaluation_result import EvaluationResult
from ..logic.traces.evaluation_result_queries import load_evaluation_results, load_output_configs
from ..logic.traces.events_fallback import fallback_window
from ..logic.traces.node import NodeEvent
from ..logic.traces.node_contents_queries import load_trace_nodes
from ..logic.traces.timeline import TimelineRow
from ..logic.traces.trace import Trace
from ..logic.traces.trace_export import (
    MAX_TRACE_EXPORT_BYTES,
    TRACE_EXPORT_FORMAT,
    TRACE_EXPORT_KIND,
    TRACE_EXPORT_NODE_BATCH_SIZE,
    TRACE_EXPORT_TTL,
    InvalidTraceExportRequestError,
    TraceExportRequest,
    TraceExportState,
    TraceExportWriter,
)
from ..logic.traces.trace_queries import TraceNodeRow, load_trace, load_trace_node, load_trace_root
from ..logic.traces.tree import TreeNode
from ..logic.traces.usage import Usage
from . import contracts


class TraceNotFoundError(Exception):
    pass


class TraceNodeNotFoundError(Exception):
    pass


class NoPassingRuleError(Exception):
    pass


class NoScoreScaleError(Exception):
    pass


_NO_METADATA = contracts.TraceNodeMetadata(
    provider=None, temperature=None, session_id=None, prompt_name=None, prompt_version=None
)


def is_usable_timestamp_hint(timestamp_hint: datetime) -> bool:
    try:
        fallback_window(timestamp_hint)
    except OverflowError:
        return False
    return True


def get_trace(team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None) -> contracts.Trace:
    loaded = load_trace(team, user, trace_id, timestamp_hint)
    if not loaded.rows:
        raise TraceNotFoundError(trace_id)
    return _to_trace(Trace(trace_id, loaded.rows, loaded.person))


def get_trace_node(
    team: Team, user: User | None, trace_id: str, node_id: str, timestamp_hint: datetime | None
) -> contracts.TraceNodeDetail:
    if node_id == trace_id:
        root = load_trace_root(team, user, trace_id, timestamp_hint)
        if not root.trace_found:
            raise TraceNodeNotFoundError(node_id)
        return _to_root_detail(trace_id, root.trace_event)
    row = load_trace_node(team, user, trace_id, node_id, timestamp_hint)
    if row is None:
        raise TraceNodeNotFoundError(node_id)
    return _to_node_detail(node_id, NodeEvent(row=row))


def _to_stats(usage: Usage) -> contracts.TraceNodeStats:
    return contracts.TraceNodeStats(
        cost_usd=usage.cost_usd,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        latency_ms=usage.latency_ms,
    )


def _to_node(node: TreeNode) -> contracts.TraceNode:
    return contracts.TraceNode(
        id=node.event.id,
        kind=node.event.kind,
        name=node.event.title,
        model=node.event.row.model,
        stats=_to_stats(node.display_usage),
        has_error=node.event.has_error,
        children=[_to_node(child) for child in node.children],
    )


def _to_timeline_row(row: TimelineRow) -> contracts.TraceTimelineRow:
    return contracts.TraceTimelineRow(
        id=row.event.id,
        kind=row.event.kind,
        name=row.event.timeline_label,
        depth=row.depth,
        start_ms=row.start_ms,
        duration_ms=row.duration_ms,
        has_error=row.event.has_error,
    )


def _to_trace(trace: Trace) -> contracts.Trace:
    totals = _to_stats(trace.totals)
    person = (
        contracts.TracePerson(distinct_id=trace.person.distinct_id, label=trace.person_label)
        if trace.person is not None and trace.person_label is not None
        else None
    )
    root = contracts.TraceNode(
        id=trace.id,
        kind="trace",
        name=trace.title,
        model=None,
        stats=totals,
        has_error=trace.has_error,
        children=[_to_node(node) for node in trace.tree],
    )
    return contracts.Trace(
        id=trace.id,
        name=trace.name,
        created_at=trace.created_at,
        session_id=trace.session_id,
        person=person,
        totals=totals,
        has_error=trace.has_error,
        error_count=trace.error_count,
        tree=[root],
        timeline=[_to_timeline_row(row) for row in trace.timeline.rows],
        total_ms=trace.timeline.total_ms,
        thread_node_ids=trace.thread_node_ids,
        default_node_id=trace.default_node_id,
        node_ids_by_alias=trace.node_ids_by_alias,
    )


def _to_root_detail(trace_id: str, trace_event: TraceNodeRow | None) -> contracts.TraceNodeDetail:
    if trace_event is None:
        return contracts.TraceNodeDetail(id=trace_id, kind="trace", error=None, metadata=_NO_METADATA, event=None)
    return _to_node_detail(trace_id, NodeEvent(row=trace_event))


def _to_node_detail(node_id: str, event: NodeEvent) -> contracts.TraceNodeDetail:
    keys = event.io_keys
    metadata = event.metadata
    return contracts.TraceNodeDetail(
        id=node_id,
        kind=event.kind,
        error=event.error,
        metadata=contracts.TraceNodeMetadata(
            provider=metadata.provider,
            temperature=metadata.temperature,
            session_id=metadata.session_id,
            prompt_name=metadata.prompt_name,
            prompt_version=metadata.prompt_version,
        ),
        event=contracts.TraceNodeEvent(
            name=event.row.event,
            uuid=event.row.uuid,
            timestamp=event.row.timestamp,
            properties=event.row.properties,
            io_keys=contracts.TraceNodeIOKeys(input=keys.input, output=keys.output, tools=keys.tools),
        ),
    )


def resolve_evaluation_pass_markers[P](properties: list[P], team_id: int) -> list[P]:
    """Replace each evaluation pass marker with the team's current condition."""
    markers = {contracts.EVALUATION_GRADED_MARKER, contracts.EVALUATION_PASSED_MARKER}
    if not any(isinstance(prop, HogQLPropertyFilter) and prop.key in markers for prop in properties):
        return properties
    filters = build_evaluation_pass_filters(team_id)
    conditions = {
        contracts.EVALUATION_GRADED_MARKER: filters.graded,
        contracts.EVALUATION_PASSED_MARKER: filters.passed,
    }
    return [
        prop.model_copy(update={"key": conditions[prop.key]})
        if isinstance(prop, HogQLPropertyFilter) and prop.key in conditions
        else prop
        for prop in properties
    ]


def mentions_evaluation_pass_markers(text: str) -> bool:
    return contracts.EVALUATION_GRADED_MARKER in text or contracts.EVALUATION_PASSED_MARKER in text


def get_trace_evaluation_results(team: Team, user: User | None, trace_id: str) -> contracts.TraceEvaluationResults:
    rows = load_evaluation_results(team, user, trace_id)
    configs = load_output_configs(team, user, {row.evaluation_id for row in rows if row.evaluation_id})
    return contracts.TraceEvaluationResults(
        results=[
            _to_evaluation_result(
                EvaluationResult.from_row(
                    row, trace_id=trace_id, output_config=configs.get(row.evaluation_id or "", {})
                )
            )
            for row in rows
        ]
    )


def _to_evaluation_result(result: EvaluationResult) -> contracts.TraceEvaluationResult:
    return contracts.TraceEvaluationResult(
        id=result.id,
        evaluation_id=result.evaluation_id,
        evaluation_name=result.name,
        target_node_id=result.target_node_id,
        outcome=result.outcome,
        label=result.label,
        reasoning=result.reasoning,
        timestamp=result.timestamp,
        is_backfill=result.is_backfill,
    )


def evaluations_period(team: Team, date_from: date | datetime | None, date_to: date | datetime | None) -> PeriodBounds:
    """Raises `InvalidPeriodError` for a period that is empty, longer than 91 days or out of range."""
    return PeriodBounds.from_request(date_from, date_to, team.timezone_info)


def get_evaluations_overview(
    team: Team, user: User | None, evaluation_ids: Sequence[str], period: PeriodBounds
) -> contracts.EvaluationsOverview:
    """Each evaluation's results in the period, compared with the period of equal length before it, plus the
    totals the overview cards show. Two ClickHouse reads, unless the evaluations group into more rows than half a
    page holds.

    While the period still runs, the previous one stops at the same point, so a partial today is not compared with
    a full day."""
    overview = overview_period(period.start, period.end, datetime.now(team.timezone_info), team.timezone_info)
    metas = load_evaluation_metas(team.pk, evaluation_ids)
    ids = [meta.id for meta in metas]
    counts = group_by_evaluation(load_bucket_counts(team, user, overview, ids, build_pass_rules(team.pk, ids)))
    categories = group_by_evaluation(
        load_category_counts(
            team, user, overview, {meta.id: len(meta.categories) for meta in metas if meta.kind == "categories"}
        )
    )
    rows = [
        evaluation_result(meta, overview.buckets, counts.get(meta.id, []), categories.get(meta.id, []))
        for meta in metas
    ]
    bucket_count = len(overview.buckets)
    return contracts.EvaluationsOverview(
        start=overview.start,
        end=overview.end,
        previous_start=overview.previous_start,
        previous_end=overview.previous_end,
        interval=overview.interval,
        buckets=list(overview.buckets),
        evaluations=rows,
        totals=overview_totals(rows, bucket_count),
        pass_rate_overview=pass_rate_overview(rows, bucket_count),
    )


def get_evaluation_runs(
    team: Team,
    user: User | None,
    evaluation_id: str,
    period: PeriodBounds,
    outcome: RunOutcome | None,
    limit: int,
) -> contracts.EvaluationRuns:
    """Raises `NoPassingRuleError` for an outcome filter on an evaluation without a passing rule."""
    if outcome is not None and load_evaluation_meta(team.pk, evaluation_id).kind != "pass_rate":
        raise NoPassingRuleError(evaluation_id)
    pass_rules = build_pass_rules(team.pk, [evaluation_id])
    return contracts.EvaluationRuns(results=load_runs(team, user, evaluation_id, period, pass_rules, outcome, limit))


def get_evaluation_score_distribution(
    team: Team, user: User | None, evaluation_id: str, period: PeriodBounds
) -> contracts.ScoreHistogram:
    """Raises `NoScoreScaleError` unless the evaluation is numeric with a minimum below its maximum."""
    meta = load_evaluation_meta(team.pk, evaluation_id)
    buckets = score_buckets(meta.scale, meta.score_step) if meta.scale is not None else None
    if meta.scale is None or buckets is None:
        raise NoScoreScaleError(evaluation_id)
    return load_score_distribution(team, user, evaluation_id, period, meta.scale, buckets)


class TraceExportNotFoundError(Exception):
    pass


class TraceExportForbiddenError(Exception):
    pass


# Allows for the workflow's own timeout plus the time it takes to record a failure.
_TRACE_EXPORT_STUCK_AFTER = EXPORT_WORKFLOW_TIMEOUT + timedelta(seconds=30)


def create_trace_export(
    team: Team, user: User, trace_id: str, timestamp_hint: datetime | None, *, was_impersonated: bool
) -> contracts.TraceExport:
    """Starts writing the trace and every node with its input and output to a JSON file the user downloads."""
    request = TraceExportRequest(trace_id=trace_id, timestamp_hint=timestamp_hint)
    asset = create_export_asset_async(
        team=team,
        created_by=user,
        export_format=TRACE_EXPORT_FORMAT,
        export_context=request.to_context(),
        expires_after=now() + TRACE_EXPORT_TTL,
    )
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=asset.id,
        scope="ExportedAsset",
        activity="exported",
        detail=Detail(
            name=asset.filename,
            type=TRACE_EXPORT_KIND,
            changes=[Change(type="ExportedAsset", action="exported", field="export_format", after=TRACE_EXPORT_FORMAT)],
        ),
    )
    return _to_trace_export(asset)


def get_trace_export(team: Team, user: User, trace_id: str, export_id: int) -> contracts.TraceExport:
    """Raises `TraceExportNotFoundError` unless the user created this export of this trace."""
    asset = get_export_asset(team_id=team.pk, asset_id=export_id)
    if (
        asset is None
        or asset.created_by_id != user.id
        or asset.export_format != TRACE_EXPORT_FORMAT
        or exported_trace_id(asset.export_context or {}) != trace_id
    ):
        raise TraceExportNotFoundError(export_id)
    return _to_trace_export(asset)


def exported_trace_id(export_context: Mapping[str, object]) -> str | None:
    try:
        return TraceExportRequest.from_context(export_context).trace_id
    except InvalidTraceExportRequestError:
        return None


def write_trace_export(team: Team, user: User, export_context: Mapping[str, object], stream: IO[bytes]) -> None:
    """Writes `contracts.TraceExportFile` as JSON to the stream, reading as the user who requested the export.

    Raises `TraceExportForbiddenError` or `TraceNotFoundError`, and the logic's `InvalidTraceExportRequestError` or
    `TraceExportTooLargeError`.
    """
    request = TraceExportRequest.from_context(export_context)
    # The export runs later without a request, so the view's permission check has to be repeated here.
    access = UserAccessControl(user=user, team=team)
    if not access.check_access_level_for_object(team, "member") or not access.check_access_level_for_resource(
        "llm_analytics", "viewer"
    ):
        raise TraceExportForbiddenError(request.trace_id)
    loaded = load_trace(team, user, request.trace_id, request.timestamp_hint, workload=Workload.OFFLINE)
    if not loaded.rows:
        raise TraceNotFoundError(request.trace_id)
    trace = Trace(request.trace_id, loaded.rows, loaded.person)
    writer = TraceExportWriter(
        stream, _to_trace(trace).model_dump_json(by_alias=True), max_bytes=MAX_TRACE_EXPORT_BYTES
    )
    root = load_trace_root(team, user, trace.id, trace.created_at, workload=Workload.OFFLINE)
    writer.add_node(_to_root_detail(trace.id, root.trace_event).model_dump_json(by_alias=True))
    for node_ids in batched([row.event.id for row in trace.timeline.rows], TRACE_EXPORT_NODE_BATCH_SIZE, strict=False):
        for row in load_trace_nodes(team, user, trace.id, node_ids, trace.created_at, workload=Workload.OFFLINE):
            writer.add_node(_to_node_detail(row.uuid, NodeEvent(row=row)).model_dump_json(by_alias=True))
    writer.close()


def _to_trace_export(asset: ExportedAsset) -> contracts.TraceExport:
    state = TraceExportState.of(
        has_content=asset.has_content,
        exception=asset.exception,
        failure_is_final=is_export_failure_final(asset),
        created_at=asset.created_at,
        now=now(),
        stuck_after=_TRACE_EXPORT_STUCK_AFTER,
    )
    return contracts.TraceExport(
        id=asset.id,
        status=state.status,
        filename=asset.filename,
        created_at=asset.created_at,
        expires_after=asset.expires_after,
        exception=state.exception,
    )
