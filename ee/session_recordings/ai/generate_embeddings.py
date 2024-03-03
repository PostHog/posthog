from django.conf import settings
from openai import OpenAI
import tiktoken

from typing import Dict, Any, List

from prometheus_client import Histogram, Counter

from posthog.models import Team

from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from ee.session_recordings.ai.utils import (
    SessionSummaryPromptData,
    reduce_elements_chain,
    simplify_window_id,
    format_dates,
    collapse_sequence_of_events,
)
from structlog import get_logger
from posthog.clickhouse.client import sync_execute
import datetime
import pytz

GENERATE_RECORDING_EMBEDDING_TIMING = Histogram(
    "posthog_session_recordings_generate_recording_embedding",
    "Time spent generating recording embeddings for a single session",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20],
)

RECORDING_EMBEDDING_TOKEN_COUNT = Histogram(
    "posthog_session_recordings_recording_embedding_token_count",
    "Token count for individual recordings generated during embedding",
    buckets=[0, 100, 500, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000],
)

SESSION_SKIPPED_WHEN_GENERATING_EMBEDDINGS = Counter(
    "posthog_session_recordings_skipped_when_generating_embeddings",
    "Number of sessions skipped when generating embeddings",
)

SESSION_EMBEDDINGS_GENERATED = Counter(
    "posthog_session_recordings_embeddings_generated",
    "Number of session embeddings generated",
)

SESSION_EMBEDDINGS_FAILED = Counter(
    "posthog_session_recordings_embeddings_failed",
    "Number of session embeddings failed",
)

SESSION_EMBEDDINGS_WRITTEN_TO_CLICKHOUSE = Counter(
    "posthog_session_recordings_embeddings_written_to_clickhouse",
    "Number of session embeddings written to Clickhouse",
)

SESSION_EMBEDDINGS_FAILED_TO_CLICKHOUSE = Counter(
    "posthog_session_recordings_embeddings_failed_to_clickhouse",
    "Number of session embeddings failed to Clickhouse",
)

logger = get_logger(__name__)

# tiktoken.encoding_for_model(model_name) specifies encoder
# model_name = "text-embedding-3-small" for this usecase
encoding = tiktoken.get_encoding("cl100k_base")

BATCH_FLUSH_SIZE = settings.REPLAY_EMBEDDINGS_BATCH_SIZE
MIN_DURATION_INCLUDE_SECONDS = settings.REPLAY_EMBEDDINGS_MIN_DURATION_SECONDS
MAX_TOKENS_FOR_MODEL = 8191


def fetch_recordings_without_embeddings(team: Team | int, offset=0) -> List[str]:
    if isinstance(team, int):
        team = Team.objects.get(id=team)

    query = """
            WITH embedding_ids AS
            (
                SELECT
                    session_id
                from
                    session_replay_embeddings
                where
                    team_id = %(team_id)s
                    -- don't load all data for all time
                    and generation_timestamp > now() - INTERVAL 7 DAY
            ),
            replay_with_events AS
            (
                SELECT
                    distinct $session_id
                from
                    events
                where
                    team_id = %(team_id)s
                    -- don't load all data for all time
                    and timestamp > now() - INTERVAL 7 DAY
                    and timestamp < now()
                    and $session_id is not null and $session_id != ''
            )
            SELECT session_id
            FROM
                session_replay_events
            WHERE
                session_id NOT IN embedding_ids
                AND team_id = %(team_id)s
                -- must be a completed session
                and min_first_timestamp < now() - INTERVAL 1 DAY
                -- let's not load all data for all time
                -- will definitely need to do something about this length of time
                and min_first_timestamp > now() - INTERVAL 7 DAY
                and session_id in replay_with_events
            GROUP BY session_id
            HAVING dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) > %(min_duration_include_seconds)s
            order by rand()
            LIMIT %(batch_flush_size)s
            -- when running locally the offset is used for paging
            -- when running in celery the offset is not used
            OFFSET %(offset)s
        """

    return [
        x[0]
        for x in sync_execute(
            query,
            {
                "team_id": team.pk,
                "batch_flush_size": BATCH_FLUSH_SIZE,
                "offset": offset,
                "min_duration_include_seconds": MIN_DURATION_INCLUDE_SECONDS,
            },
        )
    ]


def embed_batch_of_recordings(recordings: List[str], team: Team | int) -> None:
    try:
        if isinstance(team, int):
            team = Team.objects.get(id=team)

        logger.info(
            f"processing {len(recordings)} recordings to embed for team {team.pk}", flow="embeddings", team_id=team.pk
        )

        batched_embeddings = []

        for session_id in recordings:
            with GENERATE_RECORDING_EMBEDDING_TIMING.time():
                embeddings = generate_recording_embeddings(session_id=session_id, team=team)

            if embeddings:
                SESSION_EMBEDDINGS_GENERATED.inc()
                batched_embeddings.append(
                    {
                        "session_id": session_id,
                        "team_id": team.pk,
                        "embeddings": embeddings,
                    }
                )

        if len(batched_embeddings) > 0:
            flush_embeddings_to_clickhouse(embeddings=batched_embeddings)
    except Exception as e:
        SESSION_EMBEDDINGS_FAILED.inc()
        logger.error(f"embed recordings error", flow="embeddings", error=e)
        raise e


def flush_embeddings_to_clickhouse(embeddings: List[Dict[str, Any]]) -> None:
    try:
        sync_execute("INSERT INTO session_replay_embeddings (session_id, team_id, embeddings) VALUES", embeddings)
        SESSION_EMBEDDINGS_WRITTEN_TO_CLICKHOUSE.inc(len(embeddings))
    except Exception as e:
        logger.error(f"flush embeddings error", flow="embeddings", error=e)
        SESSION_EMBEDDINGS_FAILED_TO_CLICKHOUSE.inc(len(embeddings))
        raise e


def generate_recording_embeddings(session_id: str, team: Team | int) -> List[float] | None:
    logger.info(f"generating embedding for session", flow="embeddings", session_id=session_id)
    if isinstance(team, int):
        team = Team.objects.get(id=team)

    client = OpenAI()

    eight_days_ago = datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=8)
    session_metadata = SessionReplayEvents().get_metadata(
        session_id=str(session_id), team=team, recording_start_time=eight_days_ago
    )
    if not session_metadata:
        logger.error(f"no session metadata found for session", flow="embeddings", session_id=session_id)
        SESSION_SKIPPED_WHEN_GENERATING_EMBEDDINGS.inc()
        return None

    session_events = SessionReplayEvents().get_events(
        session_id=str(session_id),
        team=team,
        metadata=session_metadata,
        events_to_ignore=[
            "$feature_flag_called",
        ],
    )

    if not session_events or not session_events[0] or not session_events[1]:
        logger.error(f"no events found for session", flow="embeddings", session_id=session_id)
        SESSION_SKIPPED_WHEN_GENERATING_EMBEDDINGS.inc()
        return None

    processed_sessions = collapse_sequence_of_events(
        format_dates(
            reduce_elements_chain(
                simplify_window_id(SessionSummaryPromptData(columns=session_events[0], results=session_events[1]))
            ),
            start=datetime.datetime(1970, 1, 1, tzinfo=pytz.UTC),  # epoch timestamp
        )
    )

    logger.info(f"collapsed events for session", flow="embeddings", session_id=session_id)

    processed_sessions_index = processed_sessions.column_index("event")
    current_url_index = processed_sessions.column_index("$current_url")
    elements_chain_index = processed_sessions.column_index("elements_chain")

    input = (
        str(session_metadata)
        + "\n"
        + "\n".join(
            compact_result(
                event_name=result[processed_sessions_index] if processed_sessions_index is not None else "",
                current_url=result[current_url_index] if current_url_index is not None else "",
                elements_chain=result[elements_chain_index] if elements_chain_index is not None else "",
            )
            for result in processed_sessions.results
        )
    )

    logger.info(f"generating embedding input for session", flow="embeddings", session_id=session_id)

    token_count = num_tokens_for_input(input)
    RECORDING_EMBEDDING_TOKEN_COUNT.observe(token_count)
    if token_count > MAX_TOKENS_FOR_MODEL:
        logger.error(
            f"embedding input exceeds max token count for model", flow="embeddings", session_id=session_id, input=input
        )
        SESSION_SKIPPED_WHEN_GENERATING_EMBEDDINGS.inc()
        return None

    embeddings = (
        client.embeddings.create(
            input=input,
            model="text-embedding-3-small",
        )
        .data[0]
        .embedding
    )

    logger.info(f"generated embedding input for session", flow="embeddings", session_id=session_id)

    return embeddings


def num_tokens_for_input(string: str) -> int:
    """Returns the number of tokens in a text string."""
    return len(encoding.encode(string))


def compact_result(event_name: str, current_url: int, elements_chain: Dict[str, str] | str) -> str:
    elements_string = elements_chain if isinstance(elements_chain, str) else ", ".join(str(e) for e in elements_chain)
    return f"{event_name} {current_url} {elements_string}"
