"""Find recent session recordings eligible for video-based summarization."""

from django.conf import settings

from temporalio.exceptions import ApplicationError

from posthog.schema import HogQLQuery, PropertyOperator, RecordingPropertyFilter, RecordingsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.temporal.session_replay.count_playlist_items import convert_filters_to_recordings_query
from posthog.temporal.session_replay.summarization_sweep.constants import DEFAULT_SAMPLE_RATE, SAMPLE_RATE_PRECISION

from ee.hogai.session_summaries.constants import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S,
    SESSION_SUMMARY_EVENT_BLOCKLIST,
)

MAX_CANDIDATE_SESSIONS = 10_000


_BASELINE_HAVING_PREDICATES: list[RecordingPropertyFilter] = [
    # Ignore sessions that are too short
    RecordingPropertyFilter(
        key="active_seconds",
        operator=PropertyOperator.GTE,
        value=MIN_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S,
    ),
    # Ignore sessions that are too long
    RecordingPropertyFilter(
        key="active_seconds",
        operator=PropertyOperator.LTE,
        value=MAX_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S,
    ),
]
if not settings.DEBUG:
    _BASELINE_HAVING_PREDICATES.append(
        # Only include finished sessions
        RecordingPropertyFilter(
            key="ongoing",
            operator=PropertyOperator.EXACT,
            value=0,  # bool is represented as 0/1 in ClickHouse
        ),
    )
_DEFAULT_FILTER_TEST_ACCOUNTS = False  # Summarize all sessions (it's also faster to skip this filter)


def _build_user_defined_query(recording_filters: dict | None) -> RecordingsQuery | None:
    if not recording_filters or not isinstance(recording_filters, dict):
        return None
    try:
        return convert_filters_to_recordings_query(recording_filters)
    except Exception as e:
        capture_exception(e)
        # Include type so distinct bugs don't collapse into one Sentry group.
        raise ApplicationError(f"Error loading user defined recordings query: {type(e).__name__}: {e}") from e


def coerce_sample_rate(value: object) -> float:
    # `isinstance(True, int)` is True — reject bools so `float(True)` doesn't slip through as 1.0.
    if value is None or isinstance(value, bool):
        return DEFAULT_SAMPLE_RATE
    try:
        rate = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SAMPLE_RATE
    if rate != rate:  # NaN
        return DEFAULT_SAMPLE_RATE
    return max(0.0, min(1.0, rate))


def _sampling_having_predicate(sample_rate: float) -> ast.Expr | None:
    if sample_rate >= 1.0:
        return None
    threshold = max(0, int(sample_rate * SAMPLE_RATE_PRECISION))
    if threshold <= 0:
        return ast.Constant(value=False)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Lt,
        left=ast.Call(
            name="modulo",
            args=[
                ast.Call(name="cityHash64", args=[ast.Field(chain=["session_id"])]),
                ast.Constant(value=SAMPLE_RATE_PRECISION),
            ],
        ),
        right=ast.Constant(value=threshold),
    )


def fetch_recent_session_ids(
    team: Team,
    lookback_minutes: int,
    *,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
    recording_filters: dict | None = None,
    limit: int = MAX_CANDIDATE_SESSIONS,
    max_execution_time_seconds: int = HOGQL_INCREASED_MAX_EXECUTION_TIME,
) -> list[str]:
    """Fetch session IDs of recordings that ended within the lookback period."""
    user_defined_query = _build_user_defined_query(recording_filters)
    if user_defined_query:
        # Running a RecordingsQuery for consistency with the session recordings API
        query = RecordingsQuery(
            filter_test_accounts=user_defined_query.filter_test_accounts
            if user_defined_query.filter_test_accounts is not None
            else _DEFAULT_FILTER_TEST_ACCOUNTS,
            date_from=f"-{lookback_minutes}m",
            limit=limit,
            having_predicates=_BASELINE_HAVING_PREDICATES + (user_defined_query.having_predicates or []),
            properties=user_defined_query.properties,
            events=user_defined_query.events,
            actions=user_defined_query.actions,
            console_log_filters=user_defined_query.console_log_filters,
            operand=user_defined_query.operand,
        )
    else:
        query = RecordingsQuery(
            filter_test_accounts=_DEFAULT_FILTER_TEST_ACCOUNTS,
            date_from=f"-{lookback_minutes}m",
            limit=limit,
            having_predicates=_BASELINE_HAVING_PREDICATES,
        )

    sampling_predicate = _sampling_having_predicate(sample_rate)
    with tags_context(product=Product.SESSION_SUMMARY, feature=Feature.ENRICHMENT):
        result = SessionRecordingListFromQuery(
            team=team,
            query=query,
            max_execution_time=max_execution_time_seconds,
            extra_having_predicates=[sampling_predicate] if sampling_predicate is not None else None,
        ).run()

    return [recording["session_id"] for recording in result.results]


def filter_session_ids_with_events(
    team: Team,
    session_ids: list[str],
    lookback_minutes: int,
    max_execution_time_seconds: int = HOGQL_INCREASED_MAX_EXECUTION_TIME,
) -> set[str]:
    """Subset of `session_ids` that have at least one summarizable event in their recording window."""
    if not session_ids:
        return set()
    # Covers candidate sessions started within lookback and active up to MAX_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S.
    events_window_minutes = lookback_minutes + MAX_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S // 60 + 5
    query = HogQLQuery(
        query=(
            "SELECT DISTINCT $session_id FROM events "
            "WHERE timestamp >= now() - toIntervalMinute({events_window_minutes}) "
            "AND $session_id IN {session_ids} "
            "AND event NOT IN {events_to_ignore} "
            "LIMIT {limit}"
        ),
        values={
            "events_window_minutes": events_window_minutes,
            "session_ids": session_ids,
            "events_to_ignore": list(SESSION_SUMMARY_EVENT_BLOCKLIST),
            "limit": len(session_ids),
        },
    )
    hogql_settings = HogQLGlobalSettings(enable_analyzer=True, max_execution_time=max_execution_time_seconds)
    with tags_context(product=Product.SESSION_SUMMARY, feature=Feature.ENRICHMENT):
        result = HogQLQueryRunner(team=team, query=query, settings=hogql_settings).calculate()
    return {row[0] for row in (result.results or []) if row and row[0]}
