from django.conf import settings

from typing import List

from posthog.models import Team
from posthog.clickhouse.client import sync_execute
from ee.session_recordings.ai.generate_embeddings import ErrorEmbeddingsRunner, SessionEmbeddingsRunner

BATCH_FLUSH_SIZE = settings.REPLAY_EMBEDDINGS_BATCH_SIZE
MIN_DURATION_INCLUDE_SECONDS = settings.REPLAY_EMBEDDINGS_MIN_DURATION_SECONDS


def fetch_errors_by_session_without_embeddings(team: Team | int, offset=0) -> List[str]:
    if isinstance(team, int):
        team = Team.objects.get(id=team)

    query = """
            WITH embedded_sessions AS
            (
                SELECT
                    session_id
                from
                    session_replay_embeddings
                where
                    team_id = %(team_id)s
                    -- don't load all data for all time
                    AND generation_timestamp > now() - INTERVAL 7 DAY
                    AND source_type = 'error'
            ),
            SELECT log_source_id as session_id, message
            FROM log_entries
            PREWHERE team_id = 2
                    AND log_source = 'session_replay'
                    AND timestamp <= now()
                    AND timestamp >= now() - INTERVAL 7 DAY
                    AND session_id NOT IN embedded_sessions
            GROUP BY session_id, message
            LIMIT %(batch_flush_size)s
            -- when running locally the offset is used for paging
            -- when running in celery the offset is not used
            OFFSET %(offset)s
        """

    return sync_execute(
        query,
        {
            "team_id": team.pk,
            "batch_flush_size": BATCH_FLUSH_SIZE,
            "offset": offset,
            "min_duration_include_seconds": MIN_DURATION_INCLUDE_SECONDS,
        },
    )


def fetch_recordings_without_embeddings(team: int, offset=0) -> List[str]:
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

    return sync_execute(
        query,
        {
            "team_id": team.pk,
            "batch_flush_size": BATCH_FLUSH_SIZE,
            "offset": offset,
            "min_duration_include_seconds": MIN_DURATION_INCLUDE_SECONDS,
        },
    )


def embed_batch_of_errors(team: Team) -> None:
    results = fetch_errors_by_session_without_embeddings(team)
    ErrorEmbeddingsRunner(team=team, items=results).run()


def embed_batch_of_recordings(recordings: List[str], team: Team) -> None:
    SessionEmbeddingsRunner(team=team, items=recordings).run()
