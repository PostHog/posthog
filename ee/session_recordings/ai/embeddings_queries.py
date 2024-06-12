from django.conf import settings


from posthog.models import Team
from posthog.clickhouse.client import sync_execute

BATCH_FLUSH_SIZE = settings.REPLAY_EMBEDDINGS_BATCH_SIZE
MIN_DURATION_INCLUDE_SECONDS = settings.REPLAY_EMBEDDINGS_MIN_DURATION_SECONDS


def fetch_errors_by_session_without_embeddings(team_id: int, offset=0) -> list[str]:
    query = """
            WITH embedded_sessions AS (
                SELECT
                    session_id
                FROM
                    session_replay_embeddings
                WHERE
                    team_id = %(team_id)s
                    -- don't load all data for all time
                    AND generation_timestamp > now() - INTERVAL 7 DAY
                    AND source_type = 'error'
            )
            SELECT log_source_id, message
            FROM log_entries
            PREWHERE
                team_id = %(team_id)s
                AND level = 'error'
                AND log_source = 'session_replay'
                AND timestamp <= now()
                AND timestamp >= now() - INTERVAL 7 DAY
                AND log_source_id NOT IN embedded_sessions
            LIMIT %(batch_flush_size)s
            -- when running locally the offset is used for paging
            -- when running in celery the offset is not used
            OFFSET %(offset)s
        """

    return sync_execute(
        query,
        {
            "team_id": team_id,
            "batch_flush_size": BATCH_FLUSH_SIZE,
            "offset": offset,
        },
    )


def fetch_recordings_without_embeddings(team_id: int, offset=0) -> list[str]:
    team = Team.objects.get(id=team_id)

    query = """
            WITH embedding_ids AS
            (
                SELECT
                    session_id
                FROM
                    session_replay_embeddings
                WHERE
                    team_id = %(team_id)s
                    -- don't load all data for all time
                    AND generation_timestamp > now() - INTERVAL 7 DAY
            ),
            replay_with_events AS
            (
                SELECT
                    distinct $session_id
                FROM
                    events
                WHERE
                    team_id = %(team_id)s
                    -- don't load all data for all time
                    AND timestamp > now() - INTERVAL 7 DAY
                    AND timestamp < now()
                    AND $session_id IS NOT NULL AND $session_id != ''
            )
            SELECT session_id
            FROM
                session_replay_events
            WHERE
                session_id NOT IN embedding_ids
                AND team_id = %(team_id)s
                -- must be a completed session
                AND min_first_timestamp < now() - INTERVAL 1 DAY
                -- let's not load all data for all time
                -- will definitely need to do something about this length of time
                AND min_first_timestamp > now() - INTERVAL 7 DAY
                AND session_id IN replay_with_events
            GROUP BY session_id
            HAVING dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) > %(min_duration_include_seconds)s
            ORDER BY rand()
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
