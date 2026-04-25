"""Find recent session recordings eligible for video-based summarization."""

from django.conf import settings

from temporalio.exceptions import ApplicationError

from posthog.schema import PropertyOperator, RecordingPropertyFilter, RecordingsQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.temporal.session_replay.count_playlist_items import convert_filters_to_recordings_query

from products.signals.backend.models import SignalSourceConfig

from ee.hogai.session_summaries.constants import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SUMMARY_S,
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


class _SourceNotEnabled(Exception):
    pass


def _load_user_defined_recordings_query(team_id: int) -> RecordingsQuery | None:
    try:
        config = SignalSourceConfig.objects.get(
            team_id=team_id,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            enabled=True,
        )
    except SignalSourceConfig.DoesNotExist:
        # Config disabled mid-cycle — distinguish from the "enabled but no filters" case below.
        raise _SourceNotEnabled() from None

    try:
        recording_filters = config.config.get("recording_filters")
        if recording_filters and isinstance(recording_filters, dict):
            return convert_filters_to_recordings_query(recording_filters)
        return None
    except Exception as e:
        capture_exception(e)
        # Include type so distinct bugs don't collapse into one Sentry group.
        raise ApplicationError(f"Error loading user defined recordings query: {type(e).__name__}: {e}") from e


def fetch_recent_session_ids(
    team: Team,
    lookback_minutes: int,
    *,
    limit: int = MAX_CANDIDATE_SESSIONS,
    max_execution_time_seconds: int = HOGQL_INCREASED_MAX_EXECUTION_TIME,
) -> list[str]:
    """Fetch session IDs of recordings that ended within the lookback period."""
    try:
        user_defined_query = _load_user_defined_recordings_query(team.id)
    except _SourceNotEnabled:
        return []
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

    with tags_context(product=Product.SESSION_SUMMARY, feature=Feature.ENRICHMENT):
        result = SessionRecordingListFromQuery(
            team=team,
            query=query,
            max_execution_time=max_execution_time_seconds,
        ).run()

    return [recording["session_id"] for recording in result.results]
