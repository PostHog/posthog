from prometheus_client import Histogram

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from posthog.session_recordings.models.session_recording import SessionRecording

FIND_RECORDING_NEIGHBOURS_TIMING = Histogram(
    "posthog_session_recordings_find_recording_neighbours",
    "Time spent finding the most similar recording embeddings for a single session",
)


def similar_recordings(recording: SessionRecording, team: Team):
    with FIND_RECORDING_NEIGHBOURS_TIMING.time():
        similar_embeddings = closest_embeddings(session_id=recording.session_id, team_id=team.pk)

    # TODO: join session recording context (person, duration, etc) to show in frontend

    return similar_embeddings


def closest_embeddings(session_id: str, team_id: int):
    query = """
            WITH (
                SELECT
                    embeddings
                FROM
                    session_replay_embeddings
                WHERE
                    team_id = %(team_id)s
                    -- don't load all data for all time
                    AND generation_timestamp > now() - INTERVAL 7 DAY
                    AND session_id = %(session_id)s
                LIMIT 1
            ) as target_embeddings
            SELECT
                session_id,
                -- distance function choice based on https://help.openai.com/en/articles/6824809-embeddings-frequently-asked-questions
                -- OpenAI normalizes embeddings so L2 should produce the same score but is slightly slower
                cosineDistance(embeddings, target_embeddings) AS similarity_score
            FROM session_replay_embeddings
            WHERE
                team_id = %(team_id)s
                -- don't load all data for all time
                AND generation_timestamp > now() - INTERVAL 7 DAY
                -- skip the target recording
                AND session_id != %(session_id)s
            ORDER BY similarity_score DESC
            -- only return a max number of results
            LIMIT %(limit)s;
        """

    return sync_execute(
        query,
        {"team_id": team_id, "session_id": session_id, "limit": 3},
    )
