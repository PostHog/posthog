from posthog.models import Team, SessionRecording
from posthog.clickhouse.client import sync_execute


def similar_recordings(session_id: str, team_id: int):
    target_embeddings = find_target_embeddings(session_id=session_id, team_id=team_id)

    if target_embeddings is None:
        # TODO: generate embeddings for session
        raise

    similar_sessions = closest_embeddings(target=target_embeddings)
    return similar_sessions


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
    return result[0]


def closest_embeddings(target: [any], team: Team, recording: SessionRecording):
    query = """
            SELECT
                session_id,
                -- distance function choice based on https://help.openai.com/en/articles/6824809-embeddings-frequently-asked-questions
                -- OpenAI normalizes embeddings so L2 should produce the same score but is slightly slower
                cosine(embeddings, %(target)s) AS similarity_score
            FROM session_replay_embeddings
            WHERE
                team_id = %(team_id)s
                -- don't load all data for all time
                AND generation_timestamp > now() - INTERVAL 7 DAY
                -- skip the target recording
                AND session_id != %(session_id)s
            ORDER BY similarity_score DESC
            -- only return up to three results
            LIMIT %(batch_flush_size)s;
        """

    return sync_execute(
        query,
        {"target": target, "team_id": team.pk, "session_id": recording.id, "limit": 3},
    )
