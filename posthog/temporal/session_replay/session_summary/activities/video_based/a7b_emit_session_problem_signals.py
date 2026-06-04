import structlog
import temporalio
from structlog.contextvars import bind_contextvars

from posthog.models.team.team import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    SessionProblem,
    VideoSummarySingleSessionInputs,
    is_viewed_content_exception,
)
from posthog.temporal.session_replay.session_summary.utils import parse_str_timestamp_to_s

from products.signals.backend.facade.api import emit_signal

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import calculate_time_since_start, get_column_index, prepare_datetime

logger = structlog.get_logger(__name__)

# Events whose $current_url is within this many seconds of a problem's window still count as context for it.
_PROBLEM_WINDOW_MARGIN_S = 2.0


def _build_event_url_timeline(llm_input: SingleSessionSummaryLlmInputs) -> list[tuple[float, str]]:
    """Resolved $current_url per event, in seconds from session start, for events that carry a URL."""
    try:
        current_url_index = get_column_index(llm_input.simplified_events_columns, "$current_url")
        timestamp_index = get_column_index(llm_input.simplified_events_columns, "timestamp")
    except ValueError:
        return []
    session_start_time = prepare_datetime(llm_input.session_start_time_str)
    timeline: list[tuple[float, str]] = []
    for event_data in llm_input.simplified_events_mapping.values():
        if current_url_index >= len(event_data) or timestamp_index >= len(event_data):
            continue
        url_key = event_data[current_url_index]
        ts = event_data[timestamp_index]
        if not isinstance(url_key, str) or not isinstance(ts, str):
            continue
        event_ms = calculate_time_since_start(ts, session_start_time)
        url = llm_input.url_mapping_reversed.get(url_key, url_key)
        timeline.append((event_ms / 1000, url))
    return timeline


def _urls_in_window(timeline: list[tuple[float, str]], start_s: int, end_s: int) -> list[str]:
    return [
        url for secs, url in timeline if start_s - _PROBLEM_WINDOW_MARGIN_S <= secs <= end_s + _PROBLEM_WINDOW_MARGIN_S
    ]


def filter_viewed_content_exceptions(
    problems: list[SessionProblem], timeline: list[tuple[float, str]]
) -> tuple[list[SessionProblem], list[SessionProblem]]:
    """Split problems into (kept, suppressed), dropping exception-type problems that fired only on
    PostHog viewer surfaces — third-party errors the user was reviewing, not failures in their own flow.

    Fails open: a problem whose timestamps can't be parsed is kept rather than silently dropped.
    """
    if not timeline:
        return problems, []
    kept: list[SessionProblem] = []
    suppressed: list[SessionProblem] = []
    for problem in problems:
        try:
            start_s = parse_str_timestamp_to_s(problem.start_time)
            end_s = parse_str_timestamp_to_s(problem.end_time)
        except ValueError:
            kept.append(problem)
            continue
        urls = _urls_in_window(timeline, start_s, end_s)
        if is_viewed_content_exception(problem.problem_type, urls):
            suppressed.append(problem)
        else:
            kept.append(problem)
    return kept, suppressed


async def _suppress_viewed_content_exceptions(
    inputs: VideoSummarySingleSessionInputs, problems: list[SessionProblem]
) -> list[SessionProblem]:
    """Drop exception-type problems that occurred only on PostHog replay/error-tracking/logs surfaces.

    Reads the session's events from the same Redis state the analysis used to resolve each problem's
    on-screen URL. Fails open (keeps all problems) if the data isn't available.
    """
    try:
        redis_client, redis_input_key, _ = get_redis_state_client(
            key_base=inputs.redis_key_base,
            input_label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=inputs.session_id,
        )
        llm_input = await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            target_class=SingleSessionSummaryLlmInputs,
        )
        if llm_input is None:
            return problems
        timeline = _build_event_url_timeline(llm_input)
        kept, suppressed = filter_viewed_content_exceptions(problems, timeline)
        if suppressed:
            logger.info(
                f"Suppressed {len(suppressed)} viewed-content exception problem(s) for session {inputs.session_id}",
                session_id=inputs.session_id,
                suppressed_count=len(suppressed),
                suppressed_titles=[p.title for p in suppressed],
                signals_type="session-summaries",
            )
        return kept
    except Exception:
        # Noise-reduction filter must never block real signals — keep all problems on any failure.
        logger.exception(
            f"Failed to filter viewed-content exceptions for session {inputs.session_id}; emitting all problems",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        return problems


@temporalio.activity.defn
async def emit_session_problem_signals_activity(
    inputs: VideoSummarySingleSessionInputs,
    problems: list[SessionProblem],
    exported_asset_id: int,
) -> int:
    """Emit signals for consolidated segments that indicate user problems.

    Returns the number of signals emitted.
    """
    bind_contextvars(team_id=inputs.team_id, session_id=inputs.session_id)

    if not problems:
        return 0

    team = await Team.objects.select_related("organization").aget(id=inputs.team_id)

    if not team.organization.is_ai_data_processing_approved:
        return 0

    problems = await _suppress_viewed_content_exceptions(inputs, problems)
    if not problems:
        return 0

    session_metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(
        session_id=inputs.session_id,
        team=team,
    )

    signals_emitted = 0

    for problem in problems:
        source_id = f"{inputs.session_id}:{problem.start_time}:{problem.end_time}"

        extra: dict = {
            "session_id": inputs.session_id,
            "segment_title": problem.title,
            "start_time": problem.start_time,
            "end_time": problem.end_time,
            "problem_type": problem.problem_type,
            "distinct_id": session_metadata["distinct_id"] if session_metadata else "",
            "exported_asset_id": exported_asset_id,
        }
        if session_metadata:
            extra["session_start_time"] = session_metadata["start_time"].isoformat()
            extra["session_end_time"] = session_metadata["end_time"].isoformat()
            extra["session_duration"] = session_metadata["duration"]
            extra["session_active_seconds"] = session_metadata["active_seconds"]

        try:
            await emit_signal(
                team=team,
                source_product="session_replay",
                source_type="session_problem",
                source_id=source_id,
                description=problem.description,
                weight=1.0,  # Always research
                extra=extra,
            )
            signals_emitted += 1
            logger.debug(
                f"Emitted session problem signal for {source_id}",
                session_id=inputs.session_id,
                problem_type=problem.problem_type,
                signals_type="session-summaries",
            )
        except Exception:
            logger.exception(
                f"Failed to emit session problem signal for {source_id}",
                session_id=inputs.session_id,
                signals_type="session-summaries",
            )

    if signals_emitted > 0:
        logger.info(
            f"Emitted {signals_emitted} session problem signals for session {inputs.session_id}",
            session_id=inputs.session_id,
            signal_count=signals_emitted,
            signals_type="session-summaries",
        )

    return signals_emitted
