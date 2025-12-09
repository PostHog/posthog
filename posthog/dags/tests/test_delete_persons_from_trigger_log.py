"""Tests for the delete persons from trigger log job."""

from unittest.mock import MagicMock, patch

import psycopg2
from dagster import build_op_context

from posthog.dags.delete_persons_from_trigger_log import (
    DeletePersonsFromTriggerLogConfig,
    create_team_chunks_for_dpft,
    get_team_ids_for_dpft,
    scan_delete_chunk_for_dpft,
)


class MockPsycopg2Error(psycopg2.Error):
    """Mock psycopg2.Error that allows setting pgcode."""

    def __init__(self, message: str, pgcode: str):
        super().__init__(message)
        # Store pgcode in a private attribute
        self._pgcode = pgcode

    @property
    def pgcode(self) -> str:
        """Override pgcode property to return our custom value."""
        return self._pgcode


def create_mock_psycopg2_error(message: str, pgcode: str) -> Exception:
    """Create a mock psycopg2.Error with a specific pgcode."""
    return MockPsycopg2Error(message, pgcode)


class TestGetTeamIdsForDpft:
    """Test the get_team_ids_for_dpft function."""

    def test_get_team_ids_returns_distinct_teams(self):
        """Test that database is queried for distinct team_ids with persons to delete."""
        mock_db = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"team_id": 1}, {"team_id": 2}, {"team_id": 5}]
        mock_db.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        mock_db.cursor.return_value.__exit__ = MagicMock(return_value=False)

        context = build_op_context(resources={"database": mock_db})

        result = get_team_ids_for_dpft(context)

        assert result == [1, 2, 5]

        # Verify query was executed
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        assert any("SELECT DISTINCT pdl.team_id" in call for call in execute_calls)
        assert any("FROM posthog_person_deletes_log" in call for call in execute_calls)
        assert any("EXISTS" in call for call in execute_calls)

    def test_get_team_ids_returns_empty_list_when_no_teams(self):
        """Test that empty list is returned when no teams have persons to delete."""
        mock_db = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        mock_db.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        mock_db.cursor.return_value.__exit__ = MagicMock(return_value=False)

        context = build_op_context(resources={"database": mock_db})

        result = get_team_ids_for_dpft(context)

        assert result == []


class TestCreateTeamChunksForDpft:
    """Test the create_team_chunks_for_dpft function."""

    def test_create_chunks_for_each_team(self):
        """Test that chunks are created for each team_id."""
        team_ids = [1, 2, 5, 10]

        context = build_op_context()
        chunks = list(create_team_chunks_for_dpft(context, team_ids))

        assert len(chunks) == 4
        assert [chunk.value for chunk in chunks] == [1, 2, 5, 10]
        assert [chunk.mapping_key for chunk in chunks] == ["team_1", "team_2", "team_5", "team_10"]

    def test_create_chunks_handles_empty_team_list(self):
        """Test that no chunks are created for empty team list."""
        team_ids: list[int] = []

        context = build_op_context()
        chunks = list(create_team_chunks_for_dpft(context, team_ids))

        assert len(chunks) == 0


def create_mock_database_resource(rowcount_values=None, fetchall_results=None):
    """
    Create a mock database resource that mimics psycopg2.extensions.connection.

    Args:
        rowcount_values: List of rowcount values to return per DELETE call.
                        If None, defaults to 0. If a single int, uses that for all calls.
        fetchall_results: List of results to return from fetchall() calls (for SELECT queries).
                         Each result should be a list of dict-like objects with "id" and "team_id" keys.
                         If None, defaults to empty list.
    """
    mock_cursor = MagicMock()
    if rowcount_values is None:
        mock_cursor.rowcount = 0
    elif isinstance(rowcount_values, int):
        mock_cursor.rowcount = rowcount_values
    else:
        # Use side_effect to return different rowcounts per call
        call_count = [0]

        def get_rowcount():
            if call_count[0] < len(rowcount_values):
                result = rowcount_values[call_count[0]]
                call_count[0] += 1
                return result
            return rowcount_values[-1] if rowcount_values else 0

        mock_cursor.rowcount = property(lambda self: get_rowcount())

    mock_cursor.execute = MagicMock()
    mock_cursor.fetchone = MagicMock()

    # Setup fetchall to return scan results
    if fetchall_results is None:
        mock_cursor.fetchall = MagicMock(return_value=[])
    elif isinstance(fetchall_results, list):
        fetchall_call_count = [0]

        def get_fetchall_result():
            if fetchall_call_count[0] < len(fetchall_results):
                result = fetchall_results[fetchall_call_count[0]]
                fetchall_call_count[0] += 1
                return result
            return []

        mock_cursor.fetchall = MagicMock(side_effect=get_fetchall_result)
    else:
        mock_cursor.fetchall = MagicMock(return_value=fetchall_results)

    # Make cursor() return a context manager
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    return mock_conn


def create_mock_cluster_resource():
    """Create a mock ClickhouseCluster resource."""
    return MagicMock()


class TestScanDeleteChunkForDpft:
    """Test the scan_delete_chunk_for_dpft function."""

    def test_scan_delete_chunk_single_batch_success(self):
        """Test successful scan and delete of a single batch for a team."""
        config = DeletePersonsFromTriggerLogConfig(batch_size=100)
        team_id = 1

        # Create 50 person records to delete for this team
        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 51)]

        mock_db = create_mock_database_resource(
            rowcount_values=1,  # Each DELETE deletes 1 person
            fetchall_results=[ids_to_delete, []],  # First batch returns IDs, second returns empty (done)
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            result = scan_delete_chunk_for_dpft(context, config, team_id)

        # Verify result
        assert result["team_id"] == 1
        assert result["records_deleted"] == 50

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Verify SELECT scan query format (keyset pagination, no OFFSET)
        scan_calls = [call for call in execute_calls if "FROM posthog_person_deletes_log" in call]
        assert len(scan_calls) >= 1
        scan_query = scan_calls[0]
        assert "WHERE pdl.team_id = %s" in scan_query
        assert "ORDER BY pdl.id" in scan_query
        assert "LIMIT" in scan_query
        assert "OFFSET" not in scan_query  # Keyset pagination doesn't use OFFSET
        assert "EXISTS" in scan_query

        # Verify DELETE queries were called (one per person)
        delete_calls = [call for call in execute_calls if "DELETE FROM posthog_person_new" in call]
        assert len(delete_calls) == 50

    def test_scan_delete_chunk_multiple_batches_with_keyset_pagination(self):
        """Test scan and delete with multiple batches using keyset pagination."""
        config = DeletePersonsFromTriggerLogConfig(batch_size=50)
        team_id = 1

        # Create IDs to delete for each batch (simulate keyset pagination)
        # Batch 1: IDs 1-50, Batch 2: IDs 51-100, Batch 3: empty (done)
        fetchall_results = [
            [{"id": i, "team_id": 1} for i in range(1, 51)],
            [{"id": i, "team_id": 1} for i in range(51, 101)],
            [],  # Empty result to signal completion
        ]

        mock_db = create_mock_database_resource(
            rowcount_values=1,
            fetchall_results=fetchall_results,
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            result = scan_delete_chunk_for_dpft(context, config, team_id)

        assert result["team_id"] == 1
        assert result["records_deleted"] == 100

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Verify SELECT scan called multiple times (keyset pagination)
        scan_calls = [call for call in execute_calls if "FROM posthog_person_deletes_log" in call]
        assert len(scan_calls) >= 2

        # Second scan should include "WHERE pdl.id > %s" for keyset pagination
        if len(scan_calls) > 1:
            second_scan = scan_calls[1]
            assert "WHERE pdl.team_id = %s" in second_scan
            assert "AND pdl.id > %s" in second_scan

        # Verify DELETE called 100 times
        delete_calls = [call for call in execute_calls if "DELETE FROM posthog_person_new" in call]
        assert len(delete_calls) == 100

    def test_scan_delete_chunk_serialization_failure_retry(self):
        """Test that serialization failure triggers retry."""
        config = DeletePersonsFromTriggerLogConfig(batch_size=100)
        team_id = 1

        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_to_delete, []])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        scan_attempts = [0]

        def execute_side_effect(query, *args):
            if "FROM posthog_person_deletes_log" in query:
                scan_attempts[0] += 1
                if scan_attempts[0] == 1:
                    error = create_mock_psycopg2_error("could not serialize access", "40001")
                    raise error
            elif "DELETE FROM posthog_person_new" in query:
                cursor.rowcount = 1

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with (
            patch("posthog.dags.delete_persons_from_trigger_log.time.sleep"),
            patch.object(type(context), "run", PropertyMock(return_value=mock_run)),
        ):
            scan_delete_chunk_for_dpft(context, config, team_id)

        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        assert "ROLLBACK" in execute_calls

        scan_calls = [call for call in execute_calls if "FROM posthog_person_deletes_log" in call]
        assert len(scan_calls) >= 2

    def test_scan_delete_chunk_deadlock_retry(self):
        """Test that deadlock triggers retry."""
        config = DeletePersonsFromTriggerLogConfig(batch_size=100)
        team_id = 1

        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_to_delete, []])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        scan_attempts = [0]

        def execute_side_effect(query, *args):
            if "FROM posthog_person_deletes_log" in query:
                scan_attempts[0] += 1
                if scan_attempts[0] == 1:
                    error = create_mock_psycopg2_error("deadlock detected", "40P01")
                    raise error
            elif "DELETE FROM posthog_person_new" in query:
                cursor.rowcount = 1

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with (
            patch("posthog.dags.delete_persons_from_trigger_log.time.sleep"),
            patch.object(type(context), "run", PropertyMock(return_value=mock_run)),
        ):
            scan_delete_chunk_for_dpft(context, config, team_id)

        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        assert "ROLLBACK" in execute_calls

        scan_calls = [call for call in execute_calls if "FROM posthog_person_deletes_log" in call]
        assert len(scan_calls) >= 2

    def test_scan_delete_chunk_error_handling(self):
        """Test error handling on non-retryable errors."""
        config = DeletePersonsFromTriggerLogConfig(batch_size=100)
        team_id = 1

        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_to_delete])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        def execute_side_effect(query, *args):
            if "FROM posthog_person_deletes_log" in query:
                raise Exception("Connection lost")

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with patch.object(type(context), "run", PropertyMock(return_value=mock_run)):
            from dagster import Failure

            try:
                scan_delete_chunk_for_dpft(context, config, team_id)
                raise AssertionError("Expected Failure to be raised")
            except Failure as e:
                assert e.description is not None
                assert "team_id" in e.description

                execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
                assert "ROLLBACK" in execute_calls

    def test_scan_delete_chunk_query_format(self):
        """Test that queries have correct format for team-based processing."""
        config = DeletePersonsFromTriggerLogConfig(batch_size=100)
        team_id = 1

        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 11)]
        mock_db = create_mock_database_resource(
            rowcount_values=1,
            fetchall_results=[ids_to_delete, []],
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            scan_delete_chunk_for_dpft(context, config, team_id)

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Verify DELETE queries
        delete_queries = [call for call in execute_calls if "DELETE FROM posthog_person_new" in call]
        assert len(delete_queries) == 10

        delete_query = delete_queries[0]
        assert "DELETE FROM posthog_person_new" in delete_query
        assert "WHERE team_id = %s AND id = %s" in delete_query

        # Verify SELECT query for team-based filtering
        scan_query = next((call for call in execute_calls if "FROM posthog_person_deletes_log" in call), None)
        assert scan_query is not None
        assert "WHERE pdl.team_id = %s" in scan_query
        assert "FROM posthog_person_deletes_log" in scan_query
        assert "ORDER BY pdl.id" in scan_query
        assert "LIMIT" in scan_query
        assert "EXISTS" in scan_query
        assert "OFFSET" not in scan_query  # Keyset pagination

    def test_scan_delete_chunk_session_settings_applied_once(self):
        """Test that SET statements are applied once at session level."""
        config = DeletePersonsFromTriggerLogConfig(batch_size=50)
        team_id = 1

        fetchall_results = [
            [{"id": i, "team_id": 1} for i in range(1, 26)],
            [{"id": i, "team_id": 1} for i in range(51, 76)],
            [],
        ]
        mock_db = create_mock_database_resource(
            rowcount_values=1,
            fetchall_results=fetchall_results,
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            scan_delete_chunk_for_dpft(context, config, team_id)

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        set_statements = [
            "SET application_name",
            "SET lock_timeout",
            "SET statement_timeout",
            "SET maintenance_work_mem",
            "SET work_mem",
            "SET temp_buffers",
            "SET max_parallel_workers_per_gather",
            "SET max_parallel_maintenance_workers",
            "SET synchronous_commit",
        ]

        for stmt in set_statements:
            count = sum(1 for call in execute_calls if stmt in call)
            assert count == 1, f"Expected {stmt} to be called once, but it was called {count} times"

        # Verify SET statements come before BEGIN statements
        set_indices = [i for i, call in enumerate(execute_calls) if any(stmt in call for stmt in set_statements)]
        begin_indices = [i for i, call in enumerate(execute_calls) if call == "BEGIN"]

        if set_indices and begin_indices:
            assert max(set_indices) < min(begin_indices)
