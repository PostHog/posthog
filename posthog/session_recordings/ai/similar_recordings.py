from posthog.models import Team, SessionRecording
from posthog.clickhouse.client import sync_execute


def generate_team_embeddings(session_recording: SessionRecording, team: Team):
    recording_embeddings = find_recording_embeddings(recording=session_recording, team=team)[0]

    if recording_embeddings is None:
        # TODO: generate embeddings for a recording
        raise

    similar_sessions_ids = compare_recordings(target_embeddings=recording_embeddings)
    return similar_sessions_ids


def find_recording_embeddings(recording: SessionRecording, team: Team):
    query = """
            SELECT
                embeddings
            FROM
                session_replay_embeddings
            WHERE
                team_id = %(team_id)s
                -- don't load all data for all time
                and generation_timestamp > now() - INTERVAL 7 DAY
            LIMIT 1
        """

    return sync_execute(query, {"team_id": team.pk, "session_id": recording.id})


def compare_recordings(target_embeddings: [], team: Team, recording: SessionRecording):
    query = """
            SELECT
                session_id
            FROM
                session_replay_embeddings
            WHERE
                team_id = %(team_id)s
                -- don't load all data for all time
                and generation_timestamp > now() - INTERVAL 7 DAY
            LIMIT 1

            SELECT
                session_id,
                L2Distance(embeddings, %(target_embeddings)s) AS score
            FROM session_replay_embeddings
            WHERE
                team_id = %(team_id)s
                -- don't load all data for all time
                AND generation_timestamp > now() - INTERVAL 7 DAY
                -- don't load all data for all time
                AND session_id != %(session_id)s
            ORDER BY score DESC
            LIMIT 3;
        """

    return sync_execute(
        query,
        {
            "target_embeddings": target_embeddings,
            "team_id": team.pk,
            "session_id": recording.id,
        },
    )
