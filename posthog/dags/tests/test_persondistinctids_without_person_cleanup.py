"""Tests for the posthog_persons without distinct_ids in posthog_persondistinctid cleanup job."""

from unittest.mock import MagicMock, patch

import psycopg2
from dagster import build_op_context

from posthog.dags.persondistinctids_without_person_cleanup import (
    PersonsDistinctIdsNoPersonCleanupConfig,
    create_chunks_for_pdwp,
    get_id_range_for_pdwp,
    scan_delete_chunk_for_pdwp,
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


class TestCreateChunksForPdwp:
    """Test the create_chunks_for_pdwp function."""

    def test_create_chunks_produces_non_overlapping_ranges(self):
        """Test that chunks produce non-overlapping ranges."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(chunk_size=1000)
        id_range = (1, 5000)  # min_id=1, max_id=5000

        context = build_op_context()
        chunks = list(create_chunks_for_pdwp(context, config, id_range))

        # Extract all chunk ranges from DynamicOutput objects
        chunk_ranges = [chunk.value for chunk in chunks]

        # Verify no overlaps
        for i, (min1, max1) in enumerate(chunk_ranges):
            for j, (min2, max2) in enumerate(chunk_ranges):
                if i != j:
                    # Chunks should not overlap
                    assert not (min1 <= min2 <= max1 or min1 <= max2 <= max1 or min2 <= min1 <= max2), (
                        f"Chunks overlap: ({min1}, {max1}) and ({min2}, {max2})"
                    )

    def test_create_chunks_covers_entire_id_space(self):
        """Test that chunks cover the entire ID space from min to max."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pdwp(context, config, id_range))

        # Extract all chunk ranges from DynamicOutput objects
        chunk_ranges = [chunk.value for chunk in chunks]

        # Find the overall min and max covered
        all_ids_covered: set[int] = set()
        for chunk_min, chunk_max in chunk_ranges:
            all_ids_covered.update(range(chunk_min, chunk_max + 1))

        # Verify all IDs from min_id to max_id are covered
        expected_ids = set(range(min_id, max_id + 1))
        assert all_ids_covered == expected_ids, (
            f"Missing IDs: {expected_ids - all_ids_covered}, Extra IDs: {all_ids_covered - expected_ids}"
        )

    def test_create_chunks_first_chunk_includes_max_id(self):
        """Test that the first chunk (in yielded order) includes the source table max_id."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pdwp(context, config, id_range))

        # First chunk in the list (yielded first, highest IDs)
        first_chunk_min, first_chunk_max = chunks[0].value

        assert first_chunk_max == max_id, f"First chunk max ({first_chunk_max}) should equal source max_id ({max_id})"
        assert first_chunk_min <= max_id <= first_chunk_max, (
            f"First chunk ({first_chunk_min}, {first_chunk_max}) should include max_id ({max_id})"
        )

    def test_create_chunks_final_chunk_includes_min_id(self):
        """Test that the final chunk (in yielded order) includes the source table min_id."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pdwp(context, config, id_range))

        # Last chunk in the list (yielded last, lowest IDs)
        final_chunk_min, final_chunk_max = chunks[-1].value

        assert final_chunk_min == min_id, f"Final chunk min ({final_chunk_min}) should equal source min_id ({min_id})"
        assert final_chunk_min <= min_id <= final_chunk_max, (
            f"Final chunk ({final_chunk_min}, {final_chunk_max}) should include min_id ({min_id})"
        )

    def test_create_chunks_reverse_order(self):
        """Test that chunks are yielded in reverse order (highest IDs first)."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pdwp(context, config, id_range))

        # Verify chunks are in descending order by max_id
        for i in range(len(chunks) - 1):
            current_max = chunks[i].value[1]
            next_max = chunks[i + 1].value[1]
            assert current_max > next_max, (
                f"Chunks not in reverse order: chunk {i} max ({current_max}) should be > chunk {i + 1} max ({next_max})"
            )

    def test_create_chunks_exact_multiple(self):
        """Test chunk creation when ID range is an exact multiple of chunk_size."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(chunk_size=1000)
        min_id, max_id = 1, 5000  # Exactly 5 chunks of 1000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pdwp(context, config, id_range))

        assert len(chunks) == 5, f"Expected 5 chunks, got {len(chunks)}"

        # Verify first chunk (highest IDs)
        assert chunks[0].value == (4001, 5000), f"First chunk should be (4001, 5000), got {chunks[0].value}"

        # Verify last chunk (lowest IDs)
        assert chunks[-1].value == (1, 1000), f"Last chunk should be (1, 1000), got {chunks[-1].value}"

    def test_create_chunks_non_exact_multiple(self):
        """Test chunk creation when ID range is not an exact multiple of chunk_size."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(chunk_size=1000)
        min_id, max_id = 1, 3750  # 3 full chunks + 1 partial chunk
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pdwp(context, config, id_range))

        assert len(chunks) == 4, f"Expected 4 chunks, got {len(chunks)}"

        # Verify first chunk (highest IDs) - should be the partial chunk
        assert chunks[0].value == (3001, 3750), f"First chunk should be (3001, 3750), got {chunks[0].value}"

        # Verify last chunk (lowest IDs)
        assert chunks[-1].value == (1, 1000), f"Last chunk should be (1, 1000), got {chunks[-1].value}"

    def test_create_chunks_single_chunk(self):
        """Test chunk creation when ID range fits in a single chunk."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(chunk_size=1000)
        min_id, max_id = 100, 500
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pdwp(context, config, id_range))

        assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
        assert chunks[0].value == (100, 500), f"Chunk should be (100, 500), got {chunks[0].value}"
        assert chunks[0].value[0] == min_id and chunks[0].value[1] == max_id


def create_mock_database_resource(rowcount_values=None, fetchall_results=None):
    """
    Create a mock database resource that mimics psycopg2.extensions.connection.

    Args:
        rowcount_values: List of rowcount values to return per DELETE call.
                        If None, defaults to 0. If a single int, uses that for all calls.
        fetchall_results: List of results to return from fetchall() calls (for SELECT queries).
                         Each result should be a list of dict-like objects with "id" key.
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
            return fetchall_results[-1] if fetchall_results else []

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


class TestScanDeleteChunkForPdwp:
    """Test the scan_delete_chunk_for_pdwp function."""

    def test_scan_delete_chunk_single_batch_success(self):
        """Test successful scan and delete of a single batch within a chunk."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (1, 100)  # Single batch covers entire chunk

        # Create 50 IDs to delete (returned from DELETE...RETURNING)
        ids_deleted = [{"id": i} for i in range(1, 51)]

        # Mock: fetchall returns the deleted IDs from DELETE...RETURNING
        mock_db = create_mock_database_resource(
            fetchall_results=[ids_deleted],
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_pdwp
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            result = scan_delete_chunk_for_pdwp(context, config, chunk)

        # Verify result
        assert result["chunk_min"] == 1
        assert result["chunk_max"] == 100
        assert result["records_deleted"] == 50

        # Verify SET statements called once (session-level, before loop)
        set_statements = [
            "SET application_name = 'delete_personsdistinctids_with_no_person'",
            "SET lock_timeout = '5s'",
            "SET statement_timeout = '30min'",
            "SET work_mem = '512MB'",
            "SET temp_buffers = '512MB'",
            "SET max_parallel_workers_per_gather = 2",
            "SET max_parallel_maintenance_workers = 2",
            "SET synchronous_commit = off",
        ]

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Check SET statements were called
        for stmt in set_statements:
            assert any(stmt in call for call in execute_calls), f"SET statement not found: {stmt}"

        # Verify BEGIN and COMMIT called (single transaction with DELETE...RETURNING)
        assert execute_calls.count("BEGIN") >= 1
        assert execute_calls.count("COMMIT") >= 1

        # Verify DELETE...RETURNING query format
        delete_calls = [call for call in execute_calls if "DELETE FROM posthog_persondistinctid" in call]
        assert len(delete_calls) == 1
        delete_query = delete_calls[0]
        assert "DELETE FROM posthog_persondistinctid" in delete_query
        assert "WHERE pd.id >=" in delete_query
        assert "AND pd.id <=" in delete_query
        assert "NOT EXISTS" in delete_query
        assert "RETURNING pd.id" in delete_query

    def test_scan_delete_chunk_multiple_batches(self):
        """Test scan and delete with multiple batches in a chunk."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (1, 250)  # 3 batches: (1,100), (101,200), (201,250)

        # Create IDs deleted for each batch (returned from DELETE...RETURNING)
        # Batch 1: 50 IDs, Batch 2: 75 IDs, Batch 3: 25 IDs
        fetchall_results = [
            [{"id": i} for i in range(1, 51)],  # 50 IDs from first batch
            [{"id": i} for i in range(101, 176)],  # 75 IDs from second batch
            [{"id": i} for i in range(201, 226)],  # 25 IDs from third batch
        ]

        mock_db = create_mock_database_resource(
            fetchall_results=fetchall_results,
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_pdwp
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            result = scan_delete_chunk_for_pdwp(context, config, chunk)

        # Verify result
        assert result["chunk_min"] == 1
        assert result["chunk_max"] == 250
        assert result["records_deleted"] == 150  # 50 + 75 + 25 = 150

        # Verify SET statements called once (before loop)
        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Verify BEGIN/COMMIT called 3 times (one per batch with DELETE...RETURNING)
        assert execute_calls.count("BEGIN") >= 3
        assert execute_calls.count("COMMIT") >= 3

        # Verify DELETE...RETURNING called 3 times (one per batch)
        delete_calls = [call for call in execute_calls if "DELETE FROM posthog_persondistinctid" in call]
        assert len(delete_calls) == 3

    def test_scan_delete_chunk_serialization_failure_retry(self):
        """Test that serialization failure triggers retry."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (1, 100)

        # Create IDs to delete
        ids_deleted = [{"id": i} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_deleted])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Track DELETE query attempts
        delete_attempts = [0]

        # First DELETE query raises SerializationFailure, second succeeds
        def execute_side_effect(query, *args):
            if "DELETE FROM posthog_persondistinctid" in query:
                delete_attempts[0] += 1
                if delete_attempts[0] == 1:
                    # First attempt raises error
                    error = create_mock_psycopg2_error("could not serialize access due to concurrent update", "40001")
                    raise error
                # Second attempt succeeds - fetchall will return the IDs

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Need to patch time.sleep and run.job_name
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with (
            patch("posthog.dags.persondistinctids_without_person_cleanup.time.sleep"),
            patch.object(type(context), "run", PropertyMock(return_value=mock_run)),
        ):
            scan_delete_chunk_for_pdwp(context, config, chunk)

        # Verify ROLLBACK was called on error
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        assert "ROLLBACK" in execute_calls

        # Verify retry succeeded (should have DELETE called twice - once failed, once succeeded)
        delete_calls = [call for call in execute_calls if "DELETE FROM posthog_persondistinctid" in call]
        assert len(delete_calls) >= 2  # At least one failed attempt and one successful

    def test_scan_delete_chunk_deadlock_retry(self):
        """Test that deadlock triggers retry."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (1, 100)

        # Create IDs to delete
        ids_deleted = [{"id": i} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_deleted])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Track DELETE query attempts
        delete_attempts = [0]

        # First DELETE query raises deadlock, second succeeds
        def execute_side_effect(query, *args):
            if "DELETE FROM posthog_persondistinctid" in query:
                delete_attempts[0] += 1
                if delete_attempts[0] == 1:
                    # First attempt raises error
                    error = create_mock_psycopg2_error("deadlock detected", "40P01")
                    raise error
                # Second attempt succeeds - fetchall will return the IDs

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Need to patch time.sleep and run.job_name
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with (
            patch("posthog.dags.persondistinctids_without_person_cleanup.time.sleep"),
            patch.object(type(context), "run", PropertyMock(return_value=mock_run)),
        ):
            scan_delete_chunk_for_pdwp(context, config, chunk)

        # Verify ROLLBACK was called on error
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        assert "ROLLBACK" in execute_calls

        # Verify retry succeeded (should have DELETE called twice - once failed, once succeeded)
        delete_calls = [call for call in execute_calls if "DELETE FROM posthog_persondistinctid" in call]
        assert len(delete_calls) >= 2  # At least one failed attempt and one successful

    def test_scan_delete_chunk_error_handling_and_rollback(self):
        """Test error handling and rollback on non-retryable errors."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (1, 100)

        # Create IDs to delete
        ids_deleted = [{"id": i} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_deleted])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Raise generic error on DELETE query (non-retryable error)
        def execute_side_effect(query, *args):
            if "DELETE FROM posthog_persondistinctid" in query:
                raise Exception("Connection lost")

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with patch.object(type(context), "run", PropertyMock(return_value=mock_run)):
            # Should raise Dagster.Failure
            from dagster import Failure

            try:
                scan_delete_chunk_for_pdwp(context, config, chunk)
                raise AssertionError("Expected Dagster.Failure to be raised")
            except Failure as e:
                # Verify error metadata
                assert e.description is not None
                assert "Failed to scan and delete rows in batch" in e.description

                # Verify ROLLBACK was called
                execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
                assert "ROLLBACK" in execute_calls

    def test_scan_delete_chunk_query_format(self):
        """Test that DELETE...RETURNING query has correct format."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (1, 100)

        # Create IDs deleted (returned from DELETE...RETURNING)
        ids_deleted = [{"id": i} for i in range(1, 11)]  # 10 IDs
        mock_db = create_mock_database_resource(
            fetchall_results=[ids_deleted],
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_pdwp
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            scan_delete_chunk_for_pdwp(context, config, chunk)

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Find DELETE...RETURNING query
        delete_query = next((call for call in execute_calls if "DELETE FROM posthog_persondistinctid" in call), None)
        assert delete_query is not None

        # Verify DELETE...RETURNING query components
        assert "DELETE FROM posthog_persondistinctid pd" in delete_query
        assert "WHERE pd.id >=" in delete_query
        assert "AND pd.id <=" in delete_query
        assert "NOT EXISTS" in delete_query
        assert "RETURNING pd.id" in delete_query

    def test_scan_delete_chunk_session_settings_applied_once(self):
        """Test that SET statements are applied once at session level before batch loop."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=1000,
            batch_size=50,
        )
        chunk = (1, 150)  # 3 scan batches

        # Create IDs to delete for each scan batch
        fetchall_results = [
            [{"id": i} for i in range(1, 26)],  # 25 IDs from first scan batch
            [{"id": i} for i in range(51, 76)],  # 25 IDs from second scan batch
            [{"id": i} for i in range(101, 126)],  # 25 IDs from third scan batch
        ]
        mock_db = create_mock_database_resource(
            rowcount_values=25,
            fetchall_results=fetchall_results,
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_pdwp
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            scan_delete_chunk_for_pdwp(context, config, chunk)

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Count SET statements (should be called once each, before loop)
        set_statements = [
            "SET application_name",
            "SET lock_timeout",
            "SET statement_timeout",
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
            assert max(set_indices) < min(begin_indices), "SET statements should come before BEGIN statements"


class TestGetIdRangeForPdwp:
    """Test the get_id_range_for_pdwp function."""

    def test_get_id_range_uses_min_id_override(self):
        """Test that min_id override is honored when provided."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(min_id=100, max_id=None)
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"max_id": 5000}

        context = build_op_context(resources={"database": mock_db})

        result = get_id_range_for_pdwp(context, config)

        assert result == (100, 5000)
        assert result[0] == 100  # min_id override used

        # Verify min_id query was NOT executed (override used)
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        min_queries = [call for call in execute_calls if "MIN(id)" in call]
        assert len(min_queries) == 0, "Should not query for min_id when override is provided"

        # Verify max_id query WAS executed (queries posthog_person)
        max_queries = [call for call in execute_calls if "MAX(id)" in call and "posthog_person" in call]
        assert len(max_queries) == 1, "Should query for max_id from posthog_person when override is not provided"

    def test_get_id_range_uses_max_id_override(self):
        """Test that max_id override is honored when provided."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(min_id=1, max_id=5000)
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        context = build_op_context(resources={"database": mock_db})

        result = get_id_range_for_pdwp(context, config)

        assert result == (1, 5000)
        assert result[1] == 5000  # max_id override used

        # Verify max_id query was NOT executed (override used)
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        max_queries = [call for call in execute_calls if "MAX(id)" in call]
        assert len(max_queries) == 0, "Should not query for max_id when override is provided"

    def test_get_id_range_uses_both_overrides(self):
        """Test that both min_id and max_id overrides are honored when provided."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(min_id=100, max_id=5000)
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        context = build_op_context(resources={"database": mock_db})

        result = get_id_range_for_pdwp(context, config)

        assert result == (100, 5000)
        assert result[0] == 100  # min_id override used
        assert result[1] == 5000  # max_id override used

        # Verify NO queries were executed (both overrides used)
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        min_queries = [call for call in execute_calls if "MIN(id)" in call]
        max_queries = [call for call in execute_calls if "MAX(id)" in call]
        assert len(min_queries) == 0, "Should not query for min_id when override is provided"
        assert len(max_queries) == 0, "Should not query for max_id when override is provided"

    def test_get_id_range_queries_database_when_max_id_not_provided(self):
        """Test that database is queried for max_id when override is not provided."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(min_id=1, max_id=None)
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"max_id": 5000}

        context = build_op_context(resources={"database": mock_db})

        result = get_id_range_for_pdwp(context, config)

        assert result == (1, 5000)

        # Verify max_id query was executed (queries posthog_person)
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        max_queries = [call for call in execute_calls if "MAX(id)" in call and "posthog_person" in call]
        assert len(max_queries) == 1, "Should query for max_id from posthog_person when override is not provided"

    def test_get_id_range_validates_max_id_greater_than_min_id(self):
        """Test that validation fails when max_id < min_id."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(min_id=5000, max_id=100)
        mock_db = create_mock_database_resource()

        context = build_op_context(resources={"database": mock_db})

        from dagster import Failure

        try:
            get_id_range_for_pdwp(context, config)
            raise AssertionError("Expected Dagster.Failure to be raised")
        except Failure as e:
            assert e.description is not None
            description = e.description
            assert "max_id" in description.lower() or "invalid" in description.lower()
            assert "5000" in description or "100" in description


class TestMetricsPublishing:
    """Test metrics publishing batching behavior."""

    def test_metrics_published_every_100_batches(self):
        """Test that metrics are only published every 100 batches to reduce ClickHouse writes."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=50000,
            batch_size=100,
        )
        # Create a chunk with 250 batches (25000 records)
        chunk = (1, 25000)

        # Create fetchall results for all 250 batches
        # Each batch deletes 10 records
        fetchall_results = [[{"id": i} for i in range(batch_num * 10, batch_num * 10 + 10)] for batch_num in range(250)]

        mock_db = create_mock_database_resource(fetchall_results=fetchall_results)
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )

        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job", run_id="test_run_id")
        with patch.object(type(context), "run", PropertyMock(return_value=mock_run)):
            scan_delete_chunk_for_pdwp(context, config, chunk)

        # Get the metrics client from the cluster
        metrics_client = mock_cluster

        # Count how many times increment was called for batch metrics
        increment_calls = [
            call for call in metrics_client.method_calls if call[0] == "increment" or "increment" in str(call)
        ]

        assert len(increment_calls) < 50, (
            f"Expected metrics to be batched (~16 calls), but got {len(increment_calls)} increment calls"
        )

    def test_metrics_flushed_at_chunk_end(self):
        """Test that remaining accumulated metrics are flushed at the end of a chunk."""
        config = PersonsDistinctIdsNoPersonCleanupConfig(
            chunk_size=10000,
            batch_size=100,
        )
        # Create a chunk with 50 batches (not a multiple of 100)
        chunk = (1, 5000)

        # Create fetchall results for all 50 batches
        fetchall_results = [[{"id": i} for i in range(batch_num * 10, batch_num * 10 + 10)] for batch_num in range(50)]

        mock_db = create_mock_database_resource(fetchall_results=fetchall_results)
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )

        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job", run_id="test_run_id")
        with patch.object(type(context), "run", PropertyMock(return_value=mock_run)):
            result = scan_delete_chunk_for_pdwp(context, config, chunk)

        # Verify the chunk completed successfully
        assert result["records_deleted"] == 500  # 50 batches × 10 records each

        metrics_client = mock_cluster
        increment_calls = [
            call for call in metrics_client.method_calls if call[0] == "increment" or "increment" in str(call)
        ]

        # Should have final flush metrics
        assert len(increment_calls) > 0, "Expected metrics to be flushed at chunk end"
        assert len(increment_calls) < 20, f"Expected only final flush (~6 calls), got {len(increment_calls)}"
