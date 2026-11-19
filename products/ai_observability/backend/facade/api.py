from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from datetime import date, datetime, timedelta
from functools import partial
from itertools import batched
from typing import IO, Any, Final

from django.core.cache import cache
from django.utils.timezone import now

from posthog.schema import HogQLPropertyFilter

from posthog.clickhouse.client.connection import Workload
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.ai.ai_table_resolver import AIEventsUnavailableError
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.engineering_analytics.backend.facade import api as engineering_analytics_api
from products.engineering_analytics.backend.facade.contracts import BranchPRMatch, GitHubSourceNotConnectedError
from products.exports.backend.facade.api import (
    EXPORT_WORKFLOW_TIMEOUT,
    ExportedAsset,
    create_export_asset_async,
    get_export_asset,
    is_export_failure_final,
)
from products.surveys.backend.facade.api import (
    LinkedSurveyAnswer,
    LinkedSurveyResponse,
    LinkedSurveyResponses,
    SurveyRef,
    get_survey_responses_linked_to,
)

from ..logic.eval_suggestions import (
    config as eval_suggestions_config,
    eligibility as eval_suggestions_eligibility,
    pipeline as eval_suggestions_pipeline,
    runs as eval_suggestion_runs,
)
from ..logic.evaluations.evaluation_metas import load_evaluation_meta, load_evaluation_metas
from ..logic.evaluations.judge_preview import (
    MAX_JUDGE_TEST_UNITS as MAX_JUDGE_TEST_UNITS,
    run_judge_test,
)
from ..logic.evaluations.overview import evaluation_result, group_by_evaluation, overview_totals, pass_rate_overview
from ..logic.evaluations.overview_queries import load_bucket_counts, load_category_counts
from ..logic.evaluations.pass_filters import build_evaluation_pass_filters, build_pass_rules
from ..logic.evaluations.period import (
    InvalidPeriodError as InvalidPeriodError,
    PeriodBounds,
    overview_period,
)
from ..logic.evaluations.preview_units import (
    DEFAULT_PREVIEW_UNITS as DEFAULT_PREVIEW_UNITS,
    MAX_PREVIEW_UNITS as MAX_PREVIEW_UNITS,
    sample_traffic,
)
from ..logic.evaluations.runs import RunOutcome, load_runs
from ..logic.evaluations.score_distribution import load_score_distribution, score_buckets
from ..logic.message_normalizer.errors import RecipeCompileError as RecipeCompileError
from ..logic.message_normalizer.normalizer import RecipeNormalizer, check_stored_recipe_source, compile_candidate_recipe
from ..logic.traces import trace_metrics_queries
from ..logic.traces.cluster_queries import ClusterRunWindow, can_read_clusters, load_cluster_runs
from ..logic.traces.clusters import ClusterMemberships, TraceCluster
from ..logic.traces.dataset_item import StepDatasetItem
from ..logic.traces.evaluation_result import EvaluationResult
from ..logic.traces.evaluation_result_queries import load_evaluation_results, load_output_configs
from ..logic.traces.evaluation_summary import EvaluationSummary
from ..logic.traces.events_fallback import FallbackWindow, fallback_window, page_window
from ..logic.traces.feedback import FeedbackText, Score, StepFeedback, TraceFeedback, roll_up_by_step
from ..logic.traces.git import GitRef
from ..logic.traces.node import NodeEvent
from ..logic.traces.node_contents_queries import load_trace_nodes
from ..logic.traces.parser_verdict import parser_test_result
from ..logic.traces.person import person_label
from ..logic.traces.preview_queries import load_preview_sources
from ..logic.traces.previews import page_turns
from ..logic.traces.review import HumanReview, QueueAssignment, TraceReviewState
from ..logic.traces.review_queries import load_trace_review_state, load_trace_review_states
from ..logic.traces.sentiment_queries import TraceSentimentRow, load_sentiments
from ..logic.traces.session_queries import SessionFacts, load_has_sessions, load_session_facts
from ..logic.traces.session_selection_queries import decode_session_cursor, encode_session_cursor, load_session_page
from ..logic.traces.step_content import StepReading, read_step, step_content
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
from ..logic.traces.survey_feedback import THUMBS_UP, answer_kind, count_thumbs, survey_window
from ..logic.traces.team_recipes import save_team_recipe, team_normalizer, team_normalizer_with
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
from ..logic.traces.trace_metrics import BucketSize, MetricKey, bucket_size_for, bucket_starts, metric_value, tiles_of
from ..logic.traces.trace_metrics_queries import (
    NO_TRACES,
    TraceMetricsRows,
    TraceMetricsTooHeavyError as TraceMetricsTooHeavyError,
    previous_window,
)
from ..logic.traces.trace_queries import (
    PageTraceRows,
    PersonRow,
    TraceNodeRow,
    load_available_trace_ids,
    load_people,
    load_trace,
    load_trace_distinct_ids,
    load_trace_feedback_rows,
    load_trace_git_rows,
    load_trace_node,
    load_trace_root,
    load_trace_search,
    load_traces_rows,
)
from ..logic.traces.trace_search import TraceSearchResult
from ..logic.traces.trace_selection import (
    MAX_PROPERTY_FILTERS as MAX_PROPERTY_FILTERS,
    QUERY_SCOPED_FILTERS as QUERY_SCOPED_FILTERS,
    QUICK_FILTERS as QUICK_FILTERS,
    TRACE_ORDERS as TRACE_ORDERS,
    InvalidTraceCursorError as InvalidTraceCursorError,
    InvalidTraceSelectionError as InvalidTraceSelectionError,
    InvalidTraceWindowError as InvalidTraceWindowError,
    QuickFilter as QuickFilter,
    TraceGroupScope as TraceGroupScope,
    TracePageBounds,
    TracePosition,
    TraceSelection as TraceSelection,
    TraceWindow,
    decode_cursor,
    encode_cursor,
    resolve_window,
)
from ..logic.traces.trace_selection_queries import (
    SelectionCounts,
    SelectionPage,
    load_selection_page,
    load_trace_position,
)
from ..logic.traces.tree import TreeNode
from ..logic.traces.turn import Turn, TurnSides, Unreadable, missing_reason, preview
from ..logic.traces.turn_queries import load_turn_sources
from ..logic.traces.turn_sides import page_turn_sides
from ..logic.traces.usage import Usage
from ..temporal.trace_summary_client import start_trace_summary
from . import contracts


class TraceNotFoundError(Exception):
    pass


class TraceNotInSelectionError(Exception):
    pass


class TraceNodeNotFoundError(Exception):
    pass


class NoPassingRuleError(Exception):
    pass


class NoScoreScaleError(Exception):
    pass


TRACE_LIST_DEFAULT_LIMIT: Final = 50
TRACE_LIST_MAX_LIMIT: Final = 100
TRACE_TURNS_MAX_IDS: Final = 20
SESSION_LIST_DEFAULT_LIMIT: Final = 50
SESSION_LIST_MAX_LIMIT: Final = 100

_NO_METADATA = contracts.TraceNodeMetadata(
    provider=None, temperature=None, session_id=None, prompt_name=None, prompt_version=None
)


def is_usable_timestamp_hint(timestamp_hint: datetime) -> bool:
    try:
        fallback_window(timestamp_hint)
    except OverflowError:
        return False
    return True


def is_usable_page_bounds(earliest: datetime, latest: datetime) -> bool:
    try:
        page_window((earliest, latest))
    except OverflowError:
        return False
    return True


def get_available_trace_ids(team: Team, user: User | None, trace_ids: list[str]) -> list[str]:
    return load_available_trace_ids(team, user, trace_ids)


def get_trace(team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None) -> contracts.Trace:
    loaded = load_trace(team, user, trace_id, timestamp_hint)
    if not loaded.rows:
        raise TraceNotFoundError(trace_id)
    return _to_trace(Trace(trace_id, loaded.rows, loaded.person, partial=loaded.truncated))


def resolve_trace_window(team: Team, date_from: str | None, date_to: str | None) -> TraceWindow:
    """Raises `InvalidTraceWindowError` for a bound that does not parse or a range that ends before it starts."""
    return resolve_window(team, date_from, date_to, now())


def load_trace_list(
    team: Team,
    user: User,
    selection: TraceSelection,
    *,
    cursor: str | None,
    before_cursor: str | None,
    around: str | None,
    limit: int,
) -> Callable[[], contracts.TraceList]:
    """Loads a page of the selected traces in the selection's order, and returns the step that builds it into the list,
    each trace read the way `get_trace` reads it. `cursor` reads the page after it, `before_cursor` the page before
    it, and `around` the page that holds that trace with about half the page before it. Counts come with the first
    page of an unscoped list only.

    Raises `InvalidTraceSelectionError` when more than one of the three is sent, `InvalidTraceCursorError` for a
    cursor this read did not hand out, and `TraceNotInSelectionError` for an `around` trace the selection does not
    hold, all before the page is read.

    The step reads the traces' review states from Postgres and builds each trace, but runs no ClickHouse query. So a
    caller that holds a query concurrency slot for the load can release the slot before it runs the step.
    """
    if sum(value is not None for value in (cursor, before_cursor, around)) > 1:
        raise InvalidTraceSelectionError("Send only one of cursor, before_cursor and around.")
    if around is not None:
        page = _load_page_around(team, user, selection, around, limit)
    elif before_cursor is not None:
        page = load_selection_page(
            team, user, selection, bounds=TracePageBounds(after=None, before=decode_cursor(before_cursor)), limit=limit
        )
    else:
        after = decode_cursor(cursor) if cursor is not None else None
        page = load_selection_page(team, user, selection, bounds=TracePageBounds(after=after, before=None), limit=limit)
    loaded = _load_page_rows(team, user, page.positions)
    is_first_page = cursor is None and before_cursor is None and around is None
    return lambda: contracts.TraceList(
        items=_list_items(team, user, selection.window, page.positions, loaded),
        counts=_to_list_counts(page.counts) if is_first_page and selection.session_id is None else None,
        previous_cursor=encode_cursor(page.positions[0]) if page.has_before else None,
        next_cursor=encode_cursor(page.positions[-1]) if page.has_more else None,
    )


def _load_page_around(team: Team, user: User, selection: TraceSelection, trace_id: str, limit: int) -> SelectionPage:
    position = load_trace_position(team, user, selection, trace_id)
    if position is None:
        scope = "session" if selection.session_id is not None else "list"
        raise TraceNotInSelectionError(f"The trace is not in this {scope}.")
    before_count = limit // 2
    # A page of one slot still reads one trace before, to bound the forward read and to know there is a page before.
    before = load_selection_page(
        team, user, selection, bounds=TracePageBounds(after=None, before=position), limit=max(before_count, 1)
    )
    kept = before.positions[len(before.positions) - before_count :] if before_count else ()
    forward = load_selection_page(
        team,
        user,
        selection,
        bounds=TracePageBounds(after=before.positions[-1] if before.positions else None, before=None),
        limit=limit - len(kept),
    )
    return SelectionPage(
        positions=(*kept, *forward.positions),
        has_more=forward.has_more,
        has_before=before.has_before or len(kept) < len(before.positions),
        counts=forward.counts,
    )


def load_session_list(
    team: Team, user: User | None, selection: TraceSelection, *, cursor: str | None, limit: int
) -> Callable[[], contracts.SessionList]:
    """Loads a page of the selection's sessions, newest activity first, with each session's facts over its whole
    extent, and returns the step that builds the list. Raises `InvalidTraceCursorError` for a cursor this read did not
    hand out. A session with no events found is left out. The step runs no query."""
    page = load_session_page(
        team, user, selection, after=decode_session_cursor(cursor) if cursor is not None else None, limit=limit
    )
    read_window = selection.window.read_bounds()
    facts = load_session_facts(
        team,
        user,
        page.session_ids,
        include_support_traces=selection.include_support_traces,
        fallback=FallbackWindow(start=read_window.start, end=read_window.end),
    )
    next_cursor = encode_session_cursor(page.last_position) if page.has_more and page.last_position else None
    return lambda: contracts.SessionList(
        items=[_to_session_item(facts[session_id]) for session_id in page.session_ids if session_id in facts],
        next_cursor=next_cursor,
    )


def get_session(
    team: Team,
    user: User | None,
    session_id: str,
    *,
    hint: datetime | None,
    include_support_traces: bool = False,
) -> contracts.SessionListItem | None:
    """A session older than the AI events retention is read from the shared events table around `hint`, and is not
    found without one."""
    facts = load_session_facts(
        team,
        user,
        [session_id],
        include_support_traces=include_support_traces,
        fallback=fallback_window(hint) if hint is not None else None,
    )
    return _to_session_item(facts[session_id]) if session_id in facts else None


def has_sessions(team: Team, user: User | None) -> contracts.SessionAvailability:
    return contracts.SessionAvailability(has_sessions=load_has_sessions(team, user, now()))


def _to_session_item(facts: SessionFacts) -> contracts.SessionListItem:
    return contracts.SessionListItem(
        id=facts.session_id,
        first_seen=facts.first_seen,
        last_seen=facts.last_seen,
        duration_ms=facts.duration_ms,
        turn_count=facts.turn_count,
        totals=contracts.TraceNodeStats(
            cost_usd=facts.cost_usd,
            input_tokens=facts.input_tokens,
            output_tokens=facts.output_tokens,
            cache_read_tokens=facts.cache_read_tokens,
            cache_write_tokens=facts.cache_write_tokens,
            latency_ms=facts.wait_ms,
        ),
        errored_turns=facts.errored_turns,
        distinct_id=facts.distinct_id,
        first_trace_id=facts.first_trace_id,
        first_trace_created_at=facts.first_trace_created_at,
    )


TRACE_METRICS_CACHE_SECONDS = 300
_BUCKET_SECONDS = {BucketSize.HOUR: 3600, BucketSize.DAY: 86400}


def _metrics_cache_key(team: Team, selection: TraceSelection, size_seconds: int) -> str:
    def floored(moment: datetime) -> int:
        return int(moment.timestamp()) // size_seconds * size_seconds

    return (
        f"ai_observability_trace_metrics_v1:{team.pk}:{floored(selection.window.start)}:"
        f"{floored(selection.window.end)}:{selection.filter_test_accounts}"
    )


def load_trace_metrics(team: Team, user: User, selection: TraceSelection) -> Callable[[], contracts.TraceMetrics]:
    """Reads the totals of the selected window and of the period of the same length before it, and returns the step
    that builds them into tiles and buckets. Raises `TraceMetricsTooHeavyError` when the range is too long to compute.

    The read is cached for a few minutes, keyed by the window floored to its bucket size, so a dashboard that
    refreshes does not query ClickHouse again. The step runs no query.
    """
    window = selection.window
    size = bucket_size_for(window)
    key = _metrics_cache_key(team, selection, _BUCKET_SECONDS[size])
    rows: TraceMetricsRows | None = cache.get(key)
    if rows is None:
        rows = trace_metrics_queries.load_trace_metrics(team, user, selection, size)
        cache.set(key, rows, TRACE_METRICS_CACHE_SECONDS)
    previous = previous_window(window)
    return lambda: _to_trace_metrics(window, previous, size, rows)


def _to_trace_metrics(
    window: TraceWindow, previous: TraceWindow, size: BucketSize, rows: TraceMetricsRows
) -> contracts.TraceMetrics:
    return contracts.TraceMetrics(
        date_from=window.start,
        date_to=window.end,
        previous_date_from=previous.start,
        previous_date_to=previous.end,
        bucket_size=contracts.TraceMetricBucketSize(size.value),
        tiles=[
            contracts.TraceMetricTile(
                key=contracts.TraceMetricKey(tile.key.value),
                value=tile.value,
                previous=tile.previous,
                change=tile.change,
                change_unit=contracts.TraceMetricChangeUnit(tile.change_unit.value),
                status=contracts.TraceMetricStatus(tile.status.value),
            )
            for tile in tiles_of(rows.current, rows.previous)
        ],
        buckets=[
            contracts.TraceMetricBucket(
                start=start,
                values={
                    contracts.TraceMetricKey(key.value): metric_value(totals, key)
                    for key in MetricKey
                    for totals in [rows.buckets.get(start, NO_TRACES)]
                },
            )
            for start in bucket_starts(window, size)
        ],
    )


def _to_list_counts(counts: SelectionCounts) -> contracts.TraceListCounts:
    return contracts.TraceListCounts(total=counts.total, errors=counts.errors, feedback=counts.feedback)


def _load_page_rows(team: Team, user: User, positions: Sequence[TracePosition]) -> dict[str, PageTraceRows]:
    if not positions:
        return {}
    window = page_window([position.first_timestamp for position in positions])
    return load_traces_rows(team, user, [position.trace_id for position in positions], window)


def _list_items(
    team: Team,
    user: User,
    window: TraceWindow,
    positions: Sequence[TracePosition],
    loaded: Mapping[str, PageTraceRows],
) -> list[contracts.TraceListItem]:
    found = [position for position in positions if position.trace_id in loaded]
    reviews = load_trace_review_states(team, user, [position.trace_id for position in found])
    return [
        _to_list_item(
            Trace(
                position.trace_id,
                loaded[position.trace_id].rows,
                None,
                partial=_is_partial(window, position, loaded[position.trace_id]),
            ),
            reviews[position.trace_id],
        )
        for position in found
    ]


def _is_partial(window: TraceWindow, position: TracePosition, rows: PageTraceRows) -> bool:
    # A trace read from `posthog.ai_events` is read by id without a time bound, so only a shared table read, which is
    # bounded by the trace's first timestamp, can miss the events before it.
    return rows.truncated or (rows.from_shared_table and window.may_read_a_suffix_of(position.first_timestamp))


def load_trace_previews(
    team: Team, user: User | None, trace_ids: Sequence[str]
) -> Callable[[], contracts.TracePreviewList]:
    """Loads what the traces' input and output previews are built from, and returns the step that builds them, one per
    requested trace in request order.

    The step reads the team's recipes from Postgres and normalizes each trace's turn, but runs no ClickHouse query. So a
    caller that holds a query concurrency slot for the load can release the slot before it runs the step. A side the
    step cannot build within `PREVIEWS_TIME_LIMIT_SECONDS` for the whole page previews as null and timed out.
    """
    requested = list(dict.fromkeys(trace_ids))
    sources = load_preview_sources(team, user, requested)
    return lambda: _to_preview_list(
        requested, page_turns(sources, build_normalizer=partial(team_normalizer, team.pk), team_id=team.pk)
    )


def _to_preview_list(trace_ids: Sequence[str], turns: Mapping[str, Turn]) -> contracts.TracePreviewList:
    return contracts.TracePreviewList(items=[_to_preview(trace_id, turns.get(trace_id)) for trace_id in trace_ids])


def _to_preview(trace_id: str, turn: Turn | None) -> contracts.TracePreview:
    message = turn.message if turn else None
    answer = turn.answer if turn else None
    return contracts.TracePreview(
        trace_id=trace_id,
        input=preview(message),
        output=preview(answer),
        input_missing_reason=missing_reason(message),
        output_missing_reason=missing_reason(answer),
    )


def load_trace_turns(
    team: Team, user: User | None, trace_ids: Sequence[str], *, earliest: datetime, latest: datetime
) -> Callable[[], contracts.TraceTurnList]:
    """Loads what the traces' turns are built from, and returns the step that builds them, one per requested trace that
    was found, in request order. `earliest` and `latest` are the first timestamps of the page's earliest and latest
    traces, which bound the read of traces missing from `posthog.ai_events`.

    The step reads the team's recipes from Postgres and normalizes each turn, but runs no ClickHouse query. So a caller
    that holds a query concurrency slot for the load can release the slot before it runs the step. A side the step
    cannot build within `PREVIEWS_TIME_LIMIT_SECONDS` for the whole page is null and timed out.
    """
    requested = list(dict.fromkeys(trace_ids))
    sources = load_turn_sources(team, user, requested, earliest=earliest, latest=latest)

    def build() -> contracts.TraceTurnList:
        sides = page_turn_sides(sources, build_normalizer=partial(team_normalizer, team.pk), team_id=team.pk)
        return contracts.TraceTurnList(
            items=[_to_turn(trace_id, sides[trace_id]) for trace_id in requested if trace_id in sides]
        )

    return build


def _to_turn(trace_id: str, sides: TurnSides) -> contracts.TraceTurn:
    return contracts.TraceTurn(
        trace_id=trace_id,
        input=_readable(sides.input.value),
        output=_readable(sides.output.value),
        input_missing_reason=_reason(sides.input.unread),
        output_missing_reason=_reason(sides.output.unread),
    )


def _readable(content: contracts.TraceSideContent | None) -> contracts.TraceSideContent | None:
    if isinstance(content, contracts.TraceMessagesSide) and not content.messages:
        return None
    if isinstance(content, contracts.TraceJsonSide) and content.value is None:
        return None
    return content


def _reason(unread: Unreadable | None) -> contracts.TracePreviewMissingReason | None:
    return unread.reason if unread else None


def load_trace_people(
    team: Team, user: User | None, trace_ids: Sequence[str], *, earliest: datetime, latest: datetime
) -> contracts.TracePeopleList:
    """The person of each requested trace, in request order. `earliest` and `latest` are the first timestamps of the
    page's earliest and latest traces, which bound the read of traces missing from `posthog.ai_events`."""
    requested = list(dict.fromkeys(trace_ids))
    distinct_ids = load_trace_distinct_ids(team, user, requested, page_window((earliest, latest)))
    people = load_people(team, user, list(distinct_ids.values()))
    return contracts.TracePeopleList(
        items=[
            contracts.TracePersonItem(
                trace_id=trace_id,
                person=_to_person(people[distinct_ids[trace_id]]) if trace_id in distinct_ids else None,
            )
            for trace_id in requested
        ]
    )


def load_trace_sentiments(
    team: Team, user: User | None, trace_ids: Sequence[str], *, earliest: datetime, latest: datetime
) -> contracts.TraceSentimentList:
    """The sentiment of each requested trace, in request order. `earliest` and `latest` are the first timestamps of the
    page's earliest and latest traces, which bound the read of traces whose results may have aged out of
    `posthog.ai_events`."""
    requested = list(dict.fromkeys(trace_ids))
    sentiments = load_sentiments(team, user, requested, page_window((earliest, latest)), now())
    return contracts.TraceSentimentList(
        items=[
            contracts.TraceSentimentItem(
                trace_id=trace_id,
                sentiment=_to_sentiment(sentiments[trace_id]) if trace_id in sentiments else None,
            )
            for trace_id in requested
        ]
    )


def load_trace_node_detail(
    team: Team, user: User | None, trace_id: str, node_id: str, timestamp_hint: datetime | None
) -> Callable[[], contracts.TraceNodeDetail]:
    """Loads one node's event and returns the step that maps it to its detail.

    The step reads the team's recipes from Postgres and normalizes the node's input and output, but runs no ClickHouse
    query. So a caller that holds a query concurrency slot for the load can release the slot before it runs the step.
    """
    event = _load_node_event(team, user, trace_id, node_id, timestamp_hint)
    return lambda: _to_node_detail(team.pk, node_id, event)


def load_trace_node_raw(
    team: Team, user: User | None, trace_id: str, node_id: str, timestamp_hint: datetime | None
) -> Callable[[], contracts.TraceNodeRaw]:
    event = _load_node_event(team, user, trace_id, node_id, timestamp_hint)
    return lambda: _to_node_raw(node_id, event)


def load_trace_node_dataset_item(
    team: Team, user: User | None, trace_id: str, node_id: str, timestamp_hint: datetime
) -> Callable[[], contracts.TraceNodeDatasetItem]:
    event = _load_node_event(team, user, trace_id, node_id, timestamp_hint)
    return lambda: _to_node_dataset_item(
        StepDatasetItem(trace_id=trace_id, trace_timestamp=timestamp_hint, event=event)
    )


def run_trace_node_parser_test(
    team: Team, user: User | None, trace_id: str, node_id: str, timestamp_hint: datetime | None, source: str
) -> Callable[[], contracts.TraceNodeParserTest]:
    """Loads one node's event and returns the step that tests a parser not saved yet against it. Saves nothing.

    Raises `RecipeCompileError` before any read when the parser does not compile. The step reads the team's saved
    recipes and normalizes the node twice, without and with the parser, but runs no ClickHouse query.
    """
    candidate = compile_candidate_recipe(source)
    event = _load_node_event(team, user, trace_id, node_id, timestamp_hint)
    return lambda: _to_parser_test(team.pk, node_id, event, partial(team_normalizer_with, team.pk, candidate))


def _to_parser_test(
    team_id: int, node_id: str, event: NodeEvent | None, candidate_normalizer: Callable[[], RecipeNormalizer]
) -> contracts.TraceNodeParserTest:
    if event is None:
        return _NOTHING_TO_TEST

    def read(build_normalizer: Callable[[], RecipeNormalizer]) -> StepReading:
        return read_step(
            event.kind, node_id, event.input, event.output, build_normalizer=build_normalizer, team_id=team_id
        )

    return parser_test_result(read(partial(team_normalizer, team_id)), read(candidate_normalizer))


_NOTHING_TO_FIX: Final = contracts.TraceParserTestSide(needed_fixing=False, fixed=False, broken=False, error=None)
_NOTHING_TO_TEST: Final = contracts.TraceNodeParserTest(
    content=contracts.TraceNodeContent(
        input=contracts.TraceJsonSide(kind="json", value=None),
        output=contracts.TraceJsonSide(kind="json", value=None),
    ),
    input=_NOTHING_TO_FIX,
    output=_NOTHING_TO_FIX,
    passed=False,
)


def _load_node_event(
    team: Team, user: User | None, trace_id: str, node_id: str, timestamp_hint: datetime | None
) -> NodeEvent | None:
    """The node's event, or None for a trace root that has no event of its own."""
    if node_id == trace_id:
        root = load_trace_root(team, user, trace_id, timestamp_hint)
        if not root.trace_found:
            raise TraceNodeNotFoundError(node_id)
        return _root_event(root.trace_event)
    row = load_trace_node(team, user, trace_id, node_id, timestamp_hint)
    if row is None:
        raise TraceNodeNotFoundError(node_id)
    return NodeEvent(row=row)


def _root_event(trace_event: TraceNodeRow | None) -> NodeEvent | None:
    return NodeEvent(row=trace_event) if trace_event is not None else None


def _to_stats(usage: Usage) -> contracts.TraceNodeStats:
    return contracts.TraceNodeStats(
        cost_usd=usage.cost_usd,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        latency_ms=usage.latency_ms,
    )


def _to_node(node: TreeNode, labels: Mapping[str, str]) -> contracts.TraceNode:
    return contracts.TraceNode(
        id=node.event.id,
        kind=node.event.kind,
        name=node.event.title,
        label=labels[node.event.id],
        model=node.event.row.model,
        stats=_to_stats(node.display_usage),
        has_error=node.event.has_error,
        children=[_to_node(child, labels) for child in node.children],
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


def _to_overview(trace: Trace) -> contracts.TraceOverview:
    return contracts.TraceOverview(
        id=trace.id,
        name=trace.name,
        created_at=trace.created_at,
        session_id=trace.session_id,
        totals=_to_stats(trace.totals),
        has_error=trace.has_error,
        error_count=trace.error_count,
        totals_partial=trace.partial,
    )


def _to_list_item(trace: Trace, review: TraceReviewState) -> contracts.TraceListItem:
    return contracts.TraceListItem(
        **dict(_to_overview(trace)),
        distinct_id=trace.distinct_id,
        default_node_id=None if trace.partial else trace.default_node_id,
        first_error=trace.first_error_text,
        tools_called=list(trace.tools_called),
        is_support_trace=trace.is_support_trace,
        review=_to_review_status(review) if review.review or review.queue else None,
    )


def _to_person(person: PersonRow) -> contracts.TracePerson:
    return contracts.TracePerson(distinct_id=person.distinct_id, label=person_label(person))


def _to_sentiment(sentiment: TraceSentimentRow) -> contracts.TraceSentiment:
    return contracts.TraceSentiment(label=sentiment.label, score=sentiment.score)


def _to_trace(trace: Trace) -> contracts.Trace:
    overview = _to_overview(trace)
    person = _to_person(trace.person) if trace.person is not None and trace.person_label is not None else None
    root = contracts.TraceNode(
        id=trace.id,
        kind="trace",
        name=trace.title,
        label=trace.node_labels[trace.id],
        model=None,
        stats=overview.totals,
        has_error=trace.has_error,
        children=[_to_node(node, trace.node_labels) for node in trace.tree],
    )
    return contracts.Trace(
        **dict(overview),
        person=person,
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


def _to_node_event(event: NodeEvent) -> contracts.TraceNodeEvent:
    keys = event.io_keys
    return contracts.TraceNodeEvent(
        name=event.row.event,
        uuid=event.row.uuid,
        timestamp=event.row.timestamp,
        properties=event.row.properties,
        io_keys=contracts.TraceNodeIOKeys(input=keys.input, output=keys.output, tools=keys.tools),
    )


def _to_node_detail_event(event: NodeEvent) -> contracts.TraceNodeDetailEvent:
    return contracts.TraceNodeDetailEvent(name=event.row.event, uuid=event.row.uuid, timestamp=event.row.timestamp)


def _to_node_raw(node_id: str, event: NodeEvent | None) -> contracts.TraceNodeRaw:
    if event is None:
        return contracts.TraceNodeRaw(id=node_id, kind="trace", event=None)
    return contracts.TraceNodeRaw(id=node_id, kind=event.kind, event=_to_node_event(event))


def _to_node_dataset_item(item: StepDatasetItem) -> contracts.TraceNodeDatasetItem:
    return contracts.TraceNodeDatasetItem(
        client_item_id=item.source_event_id,
        source_trace_id=item.trace_id,
        source_event_id=item.source_event_id,
        source_timestamp=item.trace_timestamp,
        input=item.input,
        source_output=item.source_output,
        metadata=item.metadata,
    )


def _to_node_detail(team_id: int, node_id: str, event: NodeEvent | None) -> contracts.TraceNodeDetail:
    if event is None:
        return contracts.TraceNodeDetail(
            id=node_id,
            kind="trace",
            error=None,
            metadata=_NO_METADATA,
            event=None,
            content=contracts.TraceNodeContent(
                input=contracts.TraceJsonSide(kind="json", value=None),
                output=contracts.TraceJsonSide(kind="json", value=None),
            ),
        )
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
        event=_to_node_detail_event(event),
        content=step_content(
            event.kind,
            node_id,
            event.input,
            event.output,
            build_normalizer=partial(team_normalizer, team_id),
            team_id=team_id,
        ),
    )


def search_trace(
    team: Team, user: User | None, trace_id: str, query: str, timestamp_hint: datetime | None
) -> contracts.TraceSearchResults:
    """Raises `TraceNotFoundError`, and `ClickHouseQueryTimeOut` when the search outlasts its time limit."""
    loaded = load_trace_search(team, user, trace_id, query, timestamp_hint)
    if not loaded.rows:
        raise TraceNotFoundError(trace_id)
    result = TraceSearchResult.of(Trace(trace_id, loaded.rows, None), loaded.counts, query)
    return contracts.TraceSearchResults(
        total=result.total,
        matches=[contracts.TraceSearchMatch(node_id=match.node_id, count=match.count) for match in result.matches],
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
    configs = load_output_configs(team, user, {row.evaluation_uuid for row in rows if row.evaluation_uuid})
    results = [
        EvaluationResult.from_row(row, trace_id=trace_id, output_config=configs.get(row.evaluation_uuid or "", {}))
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
        label=cluster.label,
        description=cluster.description,
        is_outlier=cluster.is_outlier,
    )


NO_LINKED_SURVEYS = LinkedSurveyResponses(responses=(), unanswered=())


def get_trace_feedback(
    team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None, *, include_surveys: bool
) -> contracts.TraceFeedback:
    """End-user feedback on a trace, from its feedback events and the survey responses linked to it. An unknown trace
    has none. Survey responses are read only with `include_surveys`, and a failed survey read leaves them out."""
    rows = load_trace_feedback_rows(team, user, trace_id, timestamp_hint)
    feedback = TraceFeedback(trace_id, rows)
    survey_responses_status: contracts.TraceSurveyResponsesStatus = "ok" if include_surveys else "not_permitted"
    linked = NO_LINKED_SURVEYS
    window = survey_window(rows, timestamp_hint)
    if include_surveys and window is not None:
        try:
            linked = get_survey_responses_linked_to(
                team, user, property_name="$ai_trace_id", property_value=trace_id, since=window.start, until=window.end
            )
        except Exception as error:
            # Survey responses are one feedback source among several, so their failure must not hide the others.
            capture_exception(error)
            survey_responses_status = "failed"
    survey_responses = linked.responses
    thumbs = count_thumbs(survey_responses)
    scores = [_to_feedback_score(score) for score in feedback.scores]
    responses: list[contracts.TraceFeedbackText | contracts.TraceSurveyResponse] = sorted(
        [
            *(_to_feedback_text(text) for text in feedback.texts),
            *(_to_survey_response(response, trace_id) for response in survey_responses),
        ],
        key=lambda response: response.timestamp,
    )
    steps = roll_up_by_step(feedback.scores, [response.node_id for response in responses])
    return contracts.TraceFeedback(
        scores=scores,
        responses=responses,
        unanswered=[
            contracts.TraceUnansweredSurvey(survey=_to_survey(survey.survey), timestamp=survey.shown_at)
            for survey in linked.unanswered
        ],
        survey_responses_status=survey_responses_status,
        summary=contracts.TraceFeedbackSummary(
            total=sum(step.total for step in steps), thumbs_up=thumbs.up, thumbs_down=thumbs.down
        ),
        steps=[_to_step_feedback(step) for step in steps],
    )


def get_trace_review_status(team: Team, user: User, trace_id: str) -> contracts.TraceReviewStatus:
    """The trace's human review and the review queue it waits in, as far as the user may see them. An unknown trace
    has neither."""
    return _to_review_status(load_trace_review_state(team, user, trace_id))


def _to_review_status(state: TraceReviewState) -> contracts.TraceReviewStatus:
    return contracts.TraceReviewStatus(
        review=_to_human_review(state.review) if state.review else None,
        queue=_to_review_queue_assignment(state.queue) if state.queue else None,
    )


def _to_human_review(review: HumanReview) -> contracts.TraceHumanReview:
    return contracts.TraceHumanReview(
        reviewed_by=review.reviewed_by,
        reviewed_at=review.reviewed_at,
        comment=review.comment,
        scores=[
            contracts.TraceHumanReviewScore(name=score.name, value=score.value, label=score.label)
            for score in review.scores
        ],
    )


def _to_review_queue_assignment(queue: QueueAssignment) -> contracts.TraceReviewQueueAssignment:
    return contracts.TraceReviewQueueAssignment(id=queue.queue_id, name=queue.queue_name, item_id=queue.item_id)


def _to_feedback_score(score: Score) -> contracts.TraceFeedbackScore:
    return contracts.TraceFeedbackScore(
        id=score.id, name=score.name, value=score.value, node_id=score.node_id, timestamp=score.timestamp
    )


def _to_step_feedback(step: StepFeedback) -> contracts.TraceStepFeedback:
    return contracts.TraceStepFeedback(
        node_id=step.node_id,
        scores=[_to_feedback_score(score) for score in step.scores],
        response_count=step.response_count,
        total=step.total,
    )


def _to_feedback_text(text: FeedbackText) -> contracts.TraceFeedbackText:
    return contracts.TraceFeedbackText(
        kind="text", id=text.id, text=text.text, node_id=text.node_id, timestamp=text.timestamp
    )


def _to_survey(survey: SurveyRef) -> contracts.TraceSurvey:
    return contracts.TraceSurvey(id=survey.id, name=survey.name)


def _to_survey_response(response: LinkedSurveyResponse, trace_id: str) -> contracts.TraceSurveyResponse:
    return contracts.TraceSurveyResponse(
        kind="survey",
        id=response.submission_id,
        node_id=trace_id,
        timestamp=response.submitted_at,
        survey=_to_survey(response.survey),
        answers=[_to_survey_answer(answer) for answer in response.answers],
        complete=response.complete,
        unavailable=response.unavailable,
    )


def _to_survey_answer(answer: LinkedSurveyAnswer) -> contracts.TraceSurveyAnswer:
    question = answer.question_text
    values = list(answer.value) if isinstance(answer.value, tuple) else [answer.value]
    match answer_kind(answer):
        case "thumbs":
            return contracts.TraceThumbsAnswer(kind="thumbs", question=question, up=answer.value == THUMBS_UP)
        case "rating":
            rating = answer.rating
            return contracts.TraceRatingAnswer(
                kind="rating",
                question=question,
                value=", ".join(values),
                scale=rating.scale if rating else None,
                lower_label=rating.lower_bound_label if rating else None,
                upper_label=rating.upper_bound_label if rating else None,
            )
        case "choice":
            return contracts.TraceChoiceAnswer(kind="choice", question=question, choices=values)
        case "text":
            return contracts.TraceTextAnswer(kind="text", question=question, text=", ".join(values))


def _to_evaluation_summary(summary: EvaluationSummary) -> contracts.TraceEvaluationSummary:
    return contracts.TraceEvaluationSummary(
        passed=summary.passed,
        failed=summary.failed,
        unrated=summary.unrated,
        nodes=[
            contracts.TraceNodeEvaluationRollup(node_id=node.node_id, outcome=node.outcome) for node in summary.nodes
        ],
    )


def get_trace_pull_request(
    team: Team,
    user: User | None,
    user_access_control: "UserAccessControl | None",
    trace_id: str,
    timestamp_hint: datetime | None,
) -> contracts.TracePullRequestLookup:
    ref = GitRef.from_rows(load_trace_git_rows(team, user, trace_id, timestamp_hint))
    # A default branch is the head of unrelated pull requests, such as fork and release ones, so it links to none.
    if ref is None or ref.is_default_branch:
        return contracts.TracePullRequestLookup(pull_request=None)
    try:
        matches = engineering_analytics_api.resolve_branch(
            team=team,
            branch=ref.branch,
            repo=ref.repo,
            timestamp=ref.seen_at,
            user_access_control=user_access_control,
        )
    # The repo stamp comes from an SDK, so a value that is not owner/name reads as no match, not a failure.
    except (GitHubSourceNotConnectedError, ValueError):
        return contracts.TracePullRequestLookup(pull_request=None)
    return contracts.TracePullRequestLookup(pull_request=_to_pull_request(matches[0]) if matches else None)


def _to_pull_request(match: BranchPRMatch) -> contracts.TracePullRequest:
    owner, _, name = match.repo.partition("/")
    return contracts.TracePullRequest(repo_owner=owner, repo_name=name, number=match.number, title=match.title)


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


def sample_evaluation_traffic(
    team: Team, user: User, scope: contracts.EvaluationPreviewScope, count: int | None
) -> list[contracts.EvaluationTrafficSample]:
    """The latest units an unsaved evaluation would run on, newest first. `count` defaults to
    `DEFAULT_PREVIEW_UNITS` and is capped at what one test of the target covers."""
    try:
        return sample_traffic(team, user, scope, count)
    except AIEventsUnavailableError:
        return []


def run_unsaved_judge(
    team: Team,
    user: User,
    judge: contracts.UnsavedJudge,
    scope: contracts.EvaluationPreviewScope,
    sample_ids: Sequence[str] | None,
    *,
    reading: Callable[[], AbstractContextManager[None]] = nullcontext,
) -> list[contracts.EvaluationTestResult]:
    """Judge up to `MAX_JUDGE_TEST_UNITS` units with an unsaved LLM judge, on the team's own provider key.
    Saves nothing and emits no results. `reading` wraps each ClickHouse read, and no model call.

    Raises `contracts.JudgeModelError` and `contracts.JudgeTestAlreadyRunningError`."""
    return run_judge_test(team, user, judge, scope, sample_ids, reading=reading)


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
            failure = contracts.TraceSummaryFailure(
                reason=entry.reason, message=entry.message, retryable=entry.retryable
            )
            return contracts.TraceSummary(status="failed", content=None, failure=failure)


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
        stream,
        _to_trace(trace).model_dump_json(by_alias=True),
        truncated=loaded.truncated,
        max_bytes=MAX_TRACE_EXPORT_BYTES,
    )
    root = load_trace_root(team, user, trace.id, trace.created_at, workload=Workload.OFFLINE)
    writer.add_node(_to_node_raw(trace.id, _root_event(root.trace_event)).model_dump_json(by_alias=True))
    for node_ids in batched([row.event.id for row in trace.timeline.rows], TRACE_EXPORT_NODE_BATCH_SIZE, strict=False):
        for row in load_trace_nodes(team, user, trace.id, node_ids, trace.created_at, workload=Workload.OFFLINE):
            writer.add_node(_to_node_raw(row.uuid, NodeEvent(row=row)).model_dump_json(by_alias=True))
    writer.close()


def _to_trace_export(asset: ExportedAsset) -> contracts.TraceExport:
    state = TraceExportState.of(
        has_content=asset.has_content,
        exception=asset.exception,
        failure_is_final=is_export_failure_final(exception_type=asset.exception_type, failure_type=asset.failure_type),
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


def validate_parser_recipe_source(source: str) -> None:
    """Raises `RecipeCompileError` with a message for the author when trace reads would skip this recipe."""
    check_stored_recipe_source(source)


def create_parser_recipe(team: Team, user: User, name: str, source: str) -> str:
    """Saves a parser recipe for the team and returns its id. Raises `RecipeCompileError` when it does not compile."""
    validate_parser_recipe_source(source)
    return save_team_recipe(team.pk, user, name=name, source=source)


def eligible_clustering_team_ids(team_ids: list[int] | None = None) -> set[int]:
    from ..logic.clustering.eligibility import eligible_clustering_team_ids as eligible

    return eligible(team_ids)


def is_current_clustering_job(team_id: int, job_id: str, job_scope: str) -> bool:
    from ..logic.clustering.execution import is_current_job

    return is_current_job(team_id, job_id, job_scope)


def validate_clustering_filters(team_id: int, user: User, filters: list[dict[str, Any]]) -> None:
    from ..logic.clustering.permissions import validate_clustering_filters as validate

    validate(team_id, user, filters)


def plan_eval_suggestions() -> contracts.EvalSuggestionsPlan:
    suggestion_settings = eval_suggestions_config.load_settings()
    return contracts.EvalSuggestionsPlan(
        team_ids=eval_suggestions_eligibility.eligible_team_ids(suggestion_settings),
        max_concurrent_teams=suggestion_settings.max_concurrent_teams,
    )


def start_eval_suggestions_run(team_id: int, trigger: str, batch_id: str, run_id: str) -> str:
    team = Team.objects.get(id=team_id)
    return str(eval_suggestion_runs.create_run(team, trigger, batch_id, run_id=run_id).id)


def fail_eval_suggestions_run(team_id: int, run_id: str, error: str) -> None:
    eval_suggestion_runs.fail_run(team_id, run_id, error)


def measure_eval_suggestions(team_id: int, run_id: str, *, deadline: float) -> int:
    return eval_suggestions_pipeline.measure_stage(
        team_id, run_id, settings=eval_suggestions_config.load_settings(), deadline=deadline
    )


def screen_eval_suggestions(team_id: int, run_id: str, *, include_paid: bool, deadline: float) -> int:
    return eval_suggestions_pipeline.screen_stage(
        team_id,
        run_id,
        include_paid=include_paid,
        settings=eval_suggestions_config.load_settings(),
        deadline=deadline,
    )


def draft_eval_suggestions(team_id: int, run_id: str, *, include_paid: bool, deadline: float) -> int:
    return eval_suggestions_pipeline.draft_stage(
        team_id,
        run_id,
        include_paid=include_paid,
        settings=eval_suggestions_config.load_settings(),
        deadline=deadline,
    )


def publish_eval_suggestions(team_id: int, run_id: str) -> int:
    return eval_suggestions_pipeline.publish_stage(team_id, run_id)
