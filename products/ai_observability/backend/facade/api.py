from collections.abc import Sequence
from datetime import date, datetime

from posthog.models import Team, User

from products.ai_observability.backend.models.evaluation_configs import CategoricalOutputConfig, NumericOutputConfig
from products.ai_observability.backend.models.evaluation_outcomes import get_outcome_definition
from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationStatus

from ..logic.evaluations.overview import (
    CategoryOption,
    EvaluationMeta,
    SummaryKind,
    evaluation_result,
    group_by_evaluation,
    overview_totals,
    pass_rate_overview,
)
from ..logic.evaluations.overview_details import DetailsWindow, load_recent_failures, load_score_distribution
from ..logic.evaluations.overview_queries import load_bucket_counts, load_category_counts
from ..logic.evaluations.pass_filters import build_evaluation_pass_filters, build_pass_rules
from ..logic.evaluations.period import overview_period, resolve_bound
from ..logic.traces.evaluation_result import EvaluationResult
from ..logic.traces.evaluation_result_queries import load_evaluation_results, load_output_configs
from ..logic.traces.events_fallback import fallback_window
from ..logic.traces.node import NodeEvent
from ..logic.traces.timeline import TimelineRow
from ..logic.traces.trace import Trace
from ..logic.traces.trace_queries import load_trace, load_trace_node, load_trace_root
from ..logic.traces.tree import TreeNode
from ..logic.traces.usage import Usage
from . import contracts


class TraceNotFoundError(Exception):
    pass


class TraceNodeNotFoundError(Exception):
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
        if root.trace_event is None:
            return contracts.TraceNodeDetail(id=trace_id, kind="trace", error=None, metadata=_NO_METADATA, event=None)
        return _to_node_detail(trace_id, NodeEvent(row=root.trace_event))
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


def get_evaluation_pass_filters(team_id: int) -> contracts.EvaluationPassFilters:
    """Grade `$ai_evaluation` events with the same rules the evaluation UI applies: boolean polarity, the numeric
    or categorical passing rule, and no skipped, N/A or sentiment runs. The conditions change when an evaluation's
    output config changes, so a caller that stores them rebuilds them on `evaluation_output_changed`."""
    return build_evaluation_pass_filters(team_id)


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


def period_bound(team: Team, value: date | datetime, *, is_end: bool) -> datetime:
    """A request bound as an instant. A date is a whole day in the project's timezone, so as an end it means the
    following midnight. A datetime without an offset is read in the project's timezone."""
    return resolve_bound(value, team.timezone_info, is_end=is_end)


def get_evaluations_overview(
    team: Team, user: User | None, evaluation_ids: Sequence[str], start: datetime, end: datetime
) -> contracts.EvaluationsOverview:
    """Each evaluation's results from `start` to `end`, compared with the period of equal length before it, plus the
    totals the overview cards show. Two ClickHouse reads, unless one groups into more rows than a page holds.

    While the period still runs, the previous one stops at the same point, so a partial today is not compared with
    a full day."""
    period = overview_period(start, end, datetime.now(team.timezone_info), team.timezone_info)
    evaluations = (
        Evaluation.objects.filter(team_id=team.pk, id__in=evaluation_ids, deleted=False)
        .select_related("directory", "created_by")
        .order_by("-created_at", "id")
    )
    metas = [_evaluation_meta(evaluation) for evaluation in evaluations]
    ids = [meta.id for meta in metas]
    counts = group_by_evaluation(load_bucket_counts(team, user, period, ids, build_pass_rules(team.pk, ids)))
    categories = group_by_evaluation(
        load_category_counts(team, user, period, [meta.id for meta in metas if meta.kind == "categories"])
    )
    rows = [
        evaluation_result(meta, period.buckets, counts.get(meta.id, []), categories.get(meta.id, [])) for meta in metas
    ]
    bucket_count = len(period.buckets)
    return contracts.EvaluationsOverview(
        start=period.start,
        end=period.end,
        previous_start=period.previous_start,
        previous_end=period.previous_end,
        interval=period.interval,
        buckets=list(period.buckets),
        evaluations=rows,
        totals=overview_totals(rows, bucket_count),
        pass_rate_overview=pass_rate_overview(rows, bucket_count),
    )


def _evaluation_meta(evaluation: Evaluation) -> EvaluationMeta:
    config = evaluation.output_config or {}
    try:
        has_pass_rule = get_outcome_definition(
            evaluation.output_type, true_is_failure=config.get("true_is_failure") is True, output_config=config
        ).has_pass_rule
    except ValueError:
        has_pass_rule = False
    kind: SummaryKind
    if evaluation.output_type == "sentiment":
        kind = "sentiment"
    elif has_pass_rule:
        kind = "pass_rate"
    elif evaluation.output_type == "numeric":
        kind = "score"
    else:
        kind = "categories"
    scale = None
    score_step = None
    categories: tuple[CategoryOption, ...] = ()
    multiple = False
    # A config that no longer validates still shows its counts, without the bounds or labels it would carry.
    try:
        if evaluation.output_type == "numeric":
            numeric = NumericOutputConfig.model_validate(config)
            score_step = numeric.step
            if numeric.min is not None and numeric.max is not None:
                scale = contracts.ScoreScale(min=numeric.min, max=numeric.max)
        elif evaluation.output_type == "categorical":
            categorical = CategoricalOutputConfig.model_validate(config)
            categories = tuple(CategoryOption(key=option.key, label=option.label) for option in categorical.options)
            multiple = categorical.selection_mode == "multiple"
    except ValueError:
        pass
    creator = evaluation.created_by
    return EvaluationMeta(
        id=str(evaluation.id),
        name=evaluation.name,
        directory_name=evaluation.directory.name if evaluation.directory else None,
        evaluation_type=evaluation.evaluation_type,
        output_type=evaluation.output_type,
        enabled=evaluation.enabled,
        errored=evaluation.status == EvaluationStatus.ERROR,
        status_reason=evaluation.status_reason if evaluation.status == EvaluationStatus.ERROR else None,
        created_by=(" ".join(filter(None, [creator.first_name, creator.last_name])) or creator.email)
        if creator
        else None,
        kind=kind,
        scale=scale,
        score_step=score_step,
        categories=categories,
        multiple=multiple,
    )


def get_evaluation_overview_details(
    team: Team, user: User | None, evaluation_id: str, start: datetime, end: datetime
) -> contracts.EvaluationOverviewDetails:
    """The latest failures and the score histogram of one evaluation from `start` to `end`."""
    evaluation = Evaluation.objects.get(team_id=team.pk, id=evaluation_id, deleted=False)
    meta = _evaluation_meta(evaluation)
    window = DetailsWindow(start=start, end=end)
    return contracts.EvaluationOverviewDetails(
        evaluation_id=meta.id,
        start=start,
        end=end,
        recent_failures=load_recent_failures(team, user, meta.id, window, build_pass_rules(team.pk, [meta.id]))
        if meta.kind == "pass_rate"
        else None,
        score_distribution=load_score_distribution(team, user, meta.id, window, meta.scale, meta.score_step)
        if meta.scale is not None
        else None,
    )
