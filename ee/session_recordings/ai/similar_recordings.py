from prometheus_client import Histogram, Counter

from typing import List

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from posthog.session_recordings.models.session_recording import SessionRecording

FIND_RECORDING_NEIGHBOURS_TIMING = Histogram(
    "posthog_session_recordings_find_recording_neighbours",
    "Time spent finding the most similar recording embeddings for a single session",
)

CANNOT_FIND_NEIGHBORS_WITHOUT_EMBEDDINGS = Counter(
    "posthog_session_recordings_cannot_find_neighbours_without_embeddings",
    "Number of sessions skipped because recording didn't have embeddings",
)


def similar_recordings(recording: SessionRecording, team: Team):
    target_embeddings = find_target_embeddings(session_id=recording.session_id, team_id=team.pk)

    if target_embeddings is None:
        CANNOT_FIND_NEIGHBORS_WITHOUT_EMBEDDINGS.inc()
        return []

    with FIND_RECORDING_NEIGHBOURS_TIMING.time():
        similar_embeddings = closest_embeddings(
            target=target_embeddings, session_id=recording.session_id, team_id=team.pk
        )

    # TODO: join session recording context (person, duration, etc) to show in frontend

    return similar_embeddings


def find_target_embeddings(session_id: str, team_id: int):
    query = """
            SELECT
                embeddings
            FROM
                session_replay_embeddings
            WHERE
                team_id = %(team_id)s
                -- don't load all data for all time
                AND generation_timestamp > now() - INTERVAL 7 DAY
                -- don't load all data for all time
                AND session_id = %(session_id)s
            LIMIT 1
        """

    result = sync_execute(query, {"team_id": team_id, "session_id": session_id})
    return result[0][0] if len(result) > 0 else None


def closest_embeddings(target: List[float], session_id: str, team_id: int):
    query = """
            SELECT
                session_id,
                -- distance function choice based on https://help.openai.com/en/articles/6824809-embeddings-frequently-asked-questions
                -- OpenAI normalizes embeddings so L2 should produce the same score but is slightly slower
                cosineDistance(embeddings, %(target)s) AS similarity_score
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
        {"target": target, "team_id": team_id, "session_id": session_id, "limit": 3},
    )
