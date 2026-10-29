from collections.abc import Sequence
from datetime import date, datetime

from posthog.schema import HogQLPropertyFilter

from posthog.models import Team, User

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
from ..logic.traces.cluster_queries import ClusterRunWindow, can_read_clusters, load_cluster_runs
from ..logic.traces.clusters import ClusterMemberships, TraceCluster
from ..logic.traces.evaluation_result import EvaluationResult
from ..logic.traces.evaluation_result_queries import load_evaluation_results, load_output_configs
from ..logic.traces.evaluation_summary import EvaluationSummary
from ..logic.traces.events_fallback import fallback_window
from ..logic.traces.git import GitRef
from ..logic.traces.node import NodeEvent
from ..logic.traces.summary import (
    AIDataProcessingNotApprovedError as AIDataProcessingNotApprovedError,
    FailedSummary,
    PendingSummary,
    ReadySummary,
    SummaryEntry,
    SummaryItem,
    TraceSummaryNotFoundError as TraceSummaryNotFoundError,
    TraceSummaryRetryableError as TraceSummaryRetryableError,
)
from ..logic.traces.summary_generation import generate_summary
from ..logic.traces.summary_store import fail_abandoned_summary, request_summary, viewer_summary
from ..logic.traces.timeline import TimelineRow
from ..logic.traces.trace import Trace
from ..logic.traces.trace_queries import load_trace, load_trace_node, load_trace_root
from ..logic.traces.tree import TreeNode
from ..logic.traces.usage import Usage
from ..temporal.trace_summary_client import start_trace_summary
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
        git=_to_git(trace.git) if trace.git is not None else None,
    )


def _to_git(ref: GitRef) -> contracts.TraceGit:
    return contracts.TraceGit(branch=ref.branch, repo=ref.repo)


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
    results = [
        EvaluationResult.from_row(row, trace_id=trace_id, output_config=configs.get(row.evaluation_id or "", {}))
        for row in rows
    ]
    return contracts.TraceEvaluationResults(
        results=[_to_evaluation_result(result) for result in results],
        summary=_to_evaluation_summary(EvaluationSummary.from_results(results)),
    )


def _to_evaluation_result(result: EvaluationResult) -> contracts.TraceEvaluationResult:
    return contracts.TraceEvaluationResult(
        id=result.id,
        evaluation_id=result.evaluation_id,
        evaluation_name=result.name,
        target_node_id=result.target_node_id,
        outcome=result.outcome,
        label=result.label,
        score=result.score,
        reasoning=result.reasoning,
        timestamp=result.timestamp,
        is_backfill=result.is_backfill,
    )


def is_usable_trace_start(created_at: datetime) -> bool:
    try:
        ClusterRunWindow.for_trace(created_at)
    except OverflowError:
        return False
    return True


def get_trace_clusters(team: Team, user: User | None, trace_id: str, created_at: datetime) -> contracts.TraceClusters:
    if not can_read_clusters(team, user):
        return contracts.TraceClusters(clusters=[])
    runs = load_cluster_runs(team, user, trace_id, ClusterRunWindow.for_trace(created_at))
    return contracts.TraceClusters(
        clusters=[_to_trace_cluster(cluster) for cluster in ClusterMemberships.of(trace_id, runs).clusters]
    )


def _to_trace_cluster(cluster: TraceCluster) -> contracts.TraceCluster:
    return contracts.TraceCluster(
        run_id=cluster.run_id,
        run_at=cluster.run_at,
        job_id=cluster.job_id,
        job_name=cluster.job_name,
        cluster_id=cluster.cluster_id,
        title=cluster.title,
        description=cluster.description,
        is_outlier=cluster.is_outlier,
    )


def _to_evaluation_summary(summary: EvaluationSummary) -> contracts.TraceEvaluationSummary:
    return contracts.TraceEvaluationSummary(
        passed=summary.passed,
        failed=summary.failed,
        unrated=summary.unrated,
        nodes=[
            contracts.TraceNodeEvaluationRollup(node_id=node.node_id, outcome=node.outcome) for node in summary.nodes
        ],
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


def get_trace_summary(team: Team, user: User, trace_id: str) -> contracts.TraceSummary:
    """Raises `AIDataProcessingNotApprovedError`, or `TraceSummaryNotFoundError` when this viewer has no summary."""
    return _to_trace_summary(viewer_summary(team, user, trace_id))


def request_trace_summary(
    team: Team, user: User, trace_id: str, timestamp_hint: datetime | None, *, regenerate: bool
) -> contracts.TraceSummary:
    """A ready summary, or the pending one a job now writes. Raises `AIDataProcessingNotApprovedError`."""
    return _to_trace_summary(request_summary(team, user, trace_id, timestamp_hint, regenerate, start_trace_summary))


def generate_trace_summary(job: contracts.TraceSummaryJob, *, final_attempt: bool) -> contracts.TraceSummaryRun | None:
    """The trace summary job's body, or None when its entry no longer waits for it. Raises
    `TraceSummaryRetryableError` when a later attempt can succeed."""
    return generate_summary(job, final_attempt=final_attempt)


def fail_trace_summary(job: contracts.TraceSummaryJob) -> None:
    """Mark the job's summary failed when the job ended without writing it."""
    fail_abandoned_summary(job)


def _to_summary_items(items: tuple[SummaryItem, ...]) -> list[contracts.TraceSummaryItem]:
    return [contracts.TraceSummaryItem(text=item.text, node_id=item.node_id) for item in items]


def _to_trace_summary(entry: SummaryEntry) -> contracts.TraceSummary:
    match entry:
        case PendingSummary():
            return contracts.TraceSummary(status="pending", content=None, failure=None)
        case ReadySummary():
            content = contracts.TraceSummaryContent(
                title=entry.title,
                bullets=_to_summary_items(entry.bullets),
                notes=_to_summary_items(entry.notes),
                flow=entry.flow,
                model=entry.model,
                generated_at=entry.generated_at,
            )
            return contracts.TraceSummary(status="ready", content=content, failure=None)
        case FailedSummary():
            failure = contracts.TraceSummaryFailure(reason=entry.reason, message=entry.message)
            return contracts.TraceSummary(status="failed", content=None, failure=failure)
