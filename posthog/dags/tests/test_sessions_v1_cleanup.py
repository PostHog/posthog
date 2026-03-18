import uuid
from datetime import datetime
from functools import partial

import pytest

from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.sessions_v1_cleanup import sessions_v1_cleanup_job
from posthog.models.sessions.sql import ALLOWED_TEAM_IDS, SESSIONS_DATA_TABLE


def generate_test_prefix() -> str:
    """Generate a unique prefix for test session IDs to avoid conflicts."""
    return f"test_{uuid.uuid4().hex[:8]}"


def insert_sessions(client: Client, sessions: list[tuple[str, int, datetime]]) -> None:
    """Insert test sessions into the sessions table."""
    client.execute(
        f"""
        INSERT INTO {SESSIONS_DATA_TABLE()} (session_id, team_id, min_timestamp, max_timestamp)
        VALUES
        """,
        [(sid, tid, ts, ts) for sid, tid, ts in sessions],
    )


def count_sessions_with_prefix(prefix: str, table: str, client: Client) -> dict[int, int]:
    """Count sessions per team_id where session_id starts with prefix."""
    result = client.execute(
        f"SELECT team_id, count() FROM {table} WHERE session_id LIKE %(prefix)s GROUP BY team_id",
        {"prefix": f"{prefix}%"},
    )
    return {row[0]: row[1] for row in result} if result else {}


def get_team_ids_with_prefix(prefix: str, table: str, client: Client) -> set[int]:
    """Get all unique team_ids where session_id starts with prefix."""
    result = client.execute(
        f"SELECT DISTINCT team_id FROM {table} WHERE session_id LIKE %(prefix)s",
        {"prefix": f"{prefix}%"},
    )
    return {row[0] for row in result} if result else set()


@pytest.mark.django_db
def test_cleanup_job_deletes_non_allowed_teams(cluster: ClickhouseCluster):
    """Test that the cleanup job deletes sessions for teams not in ALLOWED_TEAM_IDS."""
    timestamp = datetime.now()
    prefix = generate_test_prefix()

    allowed_team_id = ALLOWED_TEAM_IDS[0]
    non_allowed_team_ids = [99999, 88888, 77777]

    sessions = []
    for i in range(10):
        sessions.append((f"{prefix}_allowed_{i}", allowed_team_id, timestamp))
    for team_id in non_allowed_team_ids:
        for i in range(5):
            sessions.append((f"{prefix}_non_allowed_{team_id}_{i}", team_id, timestamp))

    cluster.any_host(partial(insert_sessions, sessions=sessions)).result()

    sessions_v1_cleanup_job.execute_in_process(
        resources={"cluster": cluster},
    )

    final_counts = cluster.any_host(partial(count_sessions_with_prefix, prefix, SESSIONS_DATA_TABLE())).result()
    assert final_counts.get(allowed_team_id, 0) == 10, "Allowed team sessions should remain"
    for team_id in non_allowed_team_ids:
        assert team_id not in final_counts, f"Team {team_id} sessions should be deleted"


@pytest.mark.django_db
def test_cleanup_job_handles_empty_table(cluster: ClickhouseCluster):
    """Test that the job handles when there's nothing to delete gracefully."""
    result = sessions_v1_cleanup_job.execute_in_process(
        resources={"cluster": cluster},
    )
    assert result.success


@pytest.mark.django_db
def test_cleanup_job_handles_only_allowed_teams(cluster: ClickhouseCluster):
    """Test that the job handles a table with only allowed teams (nothing to delete)."""
    timestamp = datetime.now()
    prefix = generate_test_prefix()

    sessions = []
    for team_id in ALLOWED_TEAM_IDS[:3]:
        for i in range(5):
            sessions.append((f"{prefix}_allowed_{team_id}_{i}", team_id, timestamp))

    cluster.any_host(partial(insert_sessions, sessions=sessions)).result()

    initial_team_ids = cluster.any_host(partial(get_team_ids_with_prefix, prefix, SESSIONS_DATA_TABLE())).result()

    result = sessions_v1_cleanup_job.execute_in_process(
        resources={"cluster": cluster},
    )

    assert result.success

    final_team_ids = cluster.any_host(partial(get_team_ids_with_prefix, prefix, SESSIONS_DATA_TABLE())).result()
    assert final_team_ids == initial_team_ids


@pytest.mark.django_db
def test_delete_with_multiple_allowed_teams_in_data(cluster: ClickhouseCluster):
    """Test deletion when multiple allowed teams have data alongside non-allowed teams."""
    timestamp = datetime.now()
    prefix = generate_test_prefix()

    sessions = []
    for team_id in ALLOWED_TEAM_IDS[:5]:
        for i in range(3):
            sessions.append((f"{prefix}_allowed_{team_id}_{i}", team_id, timestamp))
    for team_id in [99999, 88888]:
        for i in range(7):
            sessions.append((f"{prefix}_non_allowed_{team_id}_{i}", team_id, timestamp))

    cluster.any_host(partial(insert_sessions, sessions=sessions)).result()

    sessions_v1_cleanup_job.execute_in_process(
        resources={"cluster": cluster},
    )

    final_counts = cluster.any_host(partial(count_sessions_with_prefix, prefix, SESSIONS_DATA_TABLE())).result()

    for team_id in ALLOWED_TEAM_IDS[:5]:
        assert final_counts.get(team_id, 0) == 3, f"Allowed team {team_id} sessions should remain"

    assert 99999 not in final_counts, "Non-allowed team 99999 should be deleted"
    assert 88888 not in final_counts, "Non-allowed team 88888 should be deleted"


class TestAllowedTeamIdsConstant:
    """Tests to verify ALLOWED_TEAM_IDS is properly configured."""

    def test_allowed_team_ids_is_not_empty(self):
        assert len(ALLOWED_TEAM_IDS) > 0

    def test_allowed_team_ids_are_integers(self):
        for team_id in ALLOWED_TEAM_IDS:
            assert isinstance(team_id, int), f"Team ID {team_id} should be an integer"

    def test_allowed_team_ids_are_positive(self):
        for team_id in ALLOWED_TEAM_IDS:
            assert team_id > 0, f"Team ID {team_id} should be positive"

    def test_allowed_team_ids_are_unique(self):
        assert len(ALLOWED_TEAM_IDS) == len(set(ALLOWED_TEAM_IDS))
