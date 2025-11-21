"""Tests for the delete persons from trigger log job."""

from unittest.mock import MagicMock, patch

import psycopg2
from dagster import build_op_context

from dags.delete_persons_from_trigger_log import (
    DeletePersonsFromTriggerLogConfig,
    create_chunks_for_dpft,
    get_scan_range_for_dpft,
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


class TestCreateChunksForDpft:
    """Test the create_chunks_for_dpft function."""

    def test_create_chunks_produces_non_overlapping_ranges(self):
        """Test that chunks produce non-overlapping ranges."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        id_range = (0, 5000)  # min_row=0, max_row=5000 (row count)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        # Extract all chunk ranges from DynamicOutput objects
        chunk_ranges = [chunk.value for chunk in chunks]

        # Verify no overlaps
        for i, (min1, max1) in enumerate(chunk_ranges):
            for j, (min2, max2) in enumerate(chunk_ranges):
                if i != j:
                    # Chunks should not overlap
                    assert not (
                        min1 <= min2 <= max1 or min1 <= max2 <= max1 or min2 <= min1 <= max2
                    ), f"Chunks overlap: ({min1}, {max1}) and ({min2}, {max2})"

    def test_create_chunks_covers_entire_row_space(self):
        """Test that chunks cover the entire row space from min to max without gaps."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        min_row, max_row = 0, 4999  # Realistic: if COUNT(*) = 5000, max_row = 4999
        id_range = (min_row, max_row)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        # Extract all chunk ranges from DynamicOutput objects
        chunk_ranges = [chunk.value for chunk in chunks]

        # Find the overall min and max covered
        all_rows_covered: set[int] = set()
        for chunk_min, chunk_max in chunk_ranges:
            all_rows_covered.update(range(chunk_min, chunk_max + 1))

        # Verify all rows from min_row to max_row are covered (inclusive)
        expected_rows = set(range(min_row, max_row + 1))
        assert all_rows_covered == expected_rows, (
            f"Missing rows: {expected_rows - all_rows_covered}, " f"Extra rows: {all_rows_covered - expected_rows}"
        )

    def test_create_chunks_non_overlapping_inclusive_coverage(self):
        """Test that chunks are non-overlapping and cover all offsets from 0 to max_row inclusively."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        # Simulate COUNT(*) = 5000, so max_row = 4999 (0-indexed)
        min_row, max_row = 0, 4999
        id_range = (min_row, max_row)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        chunk_ranges = [chunk.value for chunk in chunks]

        # Verify chunks are non-overlapping
        for i, (min1, max1) in enumerate(chunk_ranges):
            for j, (min2, max2) in enumerate(chunk_ranges):
                if i != j:
                    # Chunks should not overlap
                    assert not (
                        min1 <= min2 <= max1 or min1 <= max2 <= max1 or min2 <= min1 <= max2
                    ), f"Chunks overlap: ({min1}, {max1}) and ({min2}, {max2})"

        # Verify all offsets from 0 to max_row are covered (inclusive)
        all_offsets_covered: set[int] = set()
        for chunk_min, chunk_max in chunk_ranges:
            # Verify chunk is inclusive on both ends
            assert chunk_min <= chunk_max, f"Invalid chunk: min ({chunk_min}) > max ({chunk_max})"
            all_offsets_covered.update(range(chunk_min, chunk_max + 1))

        expected_offsets = set(range(0, max_row + 1))
        assert all_offsets_covered == expected_offsets, (
            f"Missing offsets: {sorted(expected_offsets - all_offsets_covered)}, "
            f"Extra offsets: {sorted(all_offsets_covered - expected_offsets)}"
        )

        # Verify no gaps: each chunk should start where the previous one ended + 1
        sorted_chunks = sorted(chunk_ranges, key=lambda x: x[0])
        for i in range(len(sorted_chunks) - 1):
            current_max = sorted_chunks[i][1]
            next_min = sorted_chunks[i + 1][0]
            assert (
                next_min == current_max + 1
            ), f"Gap detected: chunk {i} ends at {current_max}, chunk {i+1} starts at {next_min}"

    def test_create_chunks_first_chunk_includes_max_row(self):
        """Test that the first chunk (in yielded order) includes the source table max_row."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        min_row, max_row = 0, 4999  # Realistic: if COUNT(*) = 5000, max_row = 4999
        id_range = (min_row, max_row)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        # First chunk in the list (yielded first, highest rows)
        first_chunk_min, first_chunk_max = chunks[0].value

        assert (
            first_chunk_max == max_row
        ), f"First chunk max ({first_chunk_max}) should equal source max_row ({max_row})"
        assert (
            first_chunk_min <= max_row <= first_chunk_max
        ), f"First chunk ({first_chunk_min}, {first_chunk_max}) should include max_row ({max_row})"

    def test_create_chunks_final_chunk_includes_min_row(self):
        """Test that the final chunk (in yielded order) includes the source table min_row."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        min_row, max_row = 0, 5000
        id_range = (min_row, max_row)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        # Last chunk in the list (yielded last, lowest rows)
        final_chunk_min, final_chunk_max = chunks[-1].value

        assert (
            final_chunk_min == min_row
        ), f"Final chunk min ({final_chunk_min}) should equal source min_row ({min_row})"
        assert (
            final_chunk_min <= min_row <= final_chunk_max
        ), f"Final chunk ({final_chunk_min}, {final_chunk_max}) should include min_row ({min_row})"

    def test_create_chunks_reverse_order(self):
        """Test that chunks are yielded in reverse order (highest rows first)."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        min_row, max_row = 0, 5000
        id_range = (min_row, max_row)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        # Verify chunks are in descending order by max_row
        for i in range(len(chunks) - 1):
            current_max = chunks[i].value[1]
            next_max = chunks[i + 1].value[1]
            assert (
                current_max > next_max
            ), f"Chunks not in reverse order: chunk {i} max ({current_max}) should be > chunk {i+1} max ({next_max})"

    def test_create_chunks_exact_multiple(self):
        """Test chunk creation when row range is an exact multiple of chunk_size."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        min_row, max_row = (
            0,
            4999,
        )  # Exactly 5 chunks of 1000 rows each (0-999, 1000-1999, 2000-2999, 3000-3999, 4000-4999)
        id_range = (min_row, max_row)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        assert len(chunks) == 5, f"Expected 5 chunks, got {len(chunks)}"

        # Verify first chunk (highest rows, yielded first in reverse order)
        assert chunks[0].value == (4000, 4999), f"First chunk should be (4000, 4999), got {chunks[0].value}"

        # Verify last chunk (lowest rows, yielded last in reverse order)
        assert chunks[-1].value == (0, 999), f"Last chunk should be (0, 999), got {chunks[-1].value}"

    def test_create_chunks_non_exact_multiple(self):
        """Test chunk creation when row range is not an exact multiple of chunk_size."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        min_row, max_row = 0, 3750  # 3 full chunks + 1 partial chunk (0-999, 1000-1999, 2000-2999, 3000-3750)
        id_range = (min_row, max_row)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        assert len(chunks) == 4, f"Expected 4 chunks, got {len(chunks)}"

        # Verify first chunk (highest rows) - should be the partial chunk
        assert chunks[0].value == (3000, 3750), f"First chunk should be (3000, 3750), got {chunks[0].value}"

        # Verify last chunk (lowest rows)
        assert chunks[-1].value == (0, 999), f"Last chunk should be (0, 999), got {chunks[-1].value}"

    def test_create_chunks_single_chunk(self):
        """Test chunk creation when row range fits in a single chunk."""
        config = DeletePersonsFromTriggerLogConfig(chunk_size=1000)
        min_row, max_row = 0, 500
        id_range = (min_row, max_row)

        context = build_op_context()
        chunks = list(create_chunks_for_dpft(context, config, id_range))

        assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
        assert chunks[0].value == (0, 500), f"Chunk should be (0, 500), got {chunks[0].value}"
        assert chunks[0].value[0] == min_row and chunks[0].value[1] == max_row


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


class TestScanDeleteChunkForDpft:
    """Test the scan_delete_chunk_for_dpft function."""

    def test_scan_delete_chunk_single_batch_success(self):
        """Test successful scan and delete of a single batch within a chunk."""
        config = DeletePersonsFromTriggerLogConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (0, 100)  # Single batch covers entire chunk (row range)

        # Create 50 person records to delete - each has id and team_id
        # The scan query returns records from posthog_person_deletes_log that don't exist in posthog_person_new
        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 51)]

        # Mock: fetchall returns the IDs with team_id, DELETE returns rowcount of 1 per delete
        mock_db = create_mock_database_resource(
            rowcount_values=1,  # Each DELETE deletes 1 person
            fetchall_results=[ids_to_delete],
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_dpft
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            result = scan_delete_chunk_for_dpft(context, config, chunk)

        # Verify result
        assert result["chunk_min_row"] == 0
        assert result["chunk_max_row"] == 100
        assert result["records_deleted"] == 50  # 50 deletes, each with rowcount=1

        # Verify SET statements called once (session-level, before loop)
        set_statements = [
            "SET application_name = 'delete_persons_from_trigger_log'",
            "SET lock_timeout = '5s'",
            "SET statement_timeout = '30min'",
            "SET maintenance_work_mem = '12GB'",
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

        # Verify BEGIN, SELECT scan, COMMIT called
        # Should have: 1 BEGIN for scan, 1 COMMIT after scan, then 50 BEGIN/COMMIT pairs for deletes
        assert execute_calls.count("BEGIN") >= 51  # 1 for scan + 50 for deletes
        assert execute_calls.count("COMMIT") >= 51  # 1 for scan + 50 for deletes

        # Verify SELECT scan query format
        scan_calls = [call for call in execute_calls if "FROM posthog_person_deletes_log" in call]
        assert len(scan_calls) == 1
        scan_query = scan_calls[0]
        assert "SELECT" in scan_query
        assert "FROM posthog_person_deletes_log" in scan_query
        assert "ORDER BY pdl.id" in scan_query
        assert "LIMIT" in scan_query
        assert "OFFSET" in scan_query
        assert "EXISTS" in scan_query

        # Verify DELETE queries were called (one per person)
        delete_calls = [call for call in execute_calls if "DELETE FROM posthog_person_new" in call]
        assert len(delete_calls) == 50  # One delete per person

    def test_scan_delete_chunk_multiple_batches(self):
        """Test scan and delete with multiple batches in a chunk."""
        config = DeletePersonsFromTriggerLogConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (0, 250)  # 3 scan batches: (0,100), (101,200), (201,250)

        # Create IDs to delete for each scan batch - each needs id and team_id
        # Batch 1: 50 IDs (1-50), Batch 2: 75 IDs (101-175), Batch 3: 25 IDs (201-225)
        fetchall_results = [
            [{"id": i, "team_id": 1} for i in range(1, 51)],  # 50 IDs from first scan batch
            [{"id": i, "team_id": 1} for i in range(101, 176)],  # 75 IDs from second scan batch
            [{"id": i, "team_id": 1} for i in range(201, 226)],  # 25 IDs from third scan batch
        ]

        mock_db = create_mock_database_resource(
            rowcount_values=1,  # Each DELETE deletes 1 person
            fetchall_results=fetchall_results,
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_dpft
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            result = scan_delete_chunk_for_dpft(context, config, chunk)

        # Verify result
        assert result["chunk_min_row"] == 0
        assert result["chunk_max_row"] == 250
        assert result["records_deleted"] == 150  # 50 + 75 + 25 = 150

        # Verify SET statements called once (before loop)
        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Verify BEGIN/COMMIT called multiple times:
        # 3 scan batches: 3 BEGIN + 3 COMMIT for scans
        # 150 delete operations: 150 BEGIN + 150 COMMIT for deletes (one per person)
        # Total: 153 BEGIN, 153 COMMIT
        assert execute_calls.count("BEGIN") >= 153  # 3 scans + 150 deletes
        assert execute_calls.count("COMMIT") >= 153  # 3 scans + 150 deletes

        # Verify SELECT scan called 3 times (one per scan batch)
        scan_calls = [call for call in execute_calls if "FROM posthog_person_deletes_log" in call]
        assert len(scan_calls) == 3

        # Verify DELETE called 150 times (one per person)
        delete_calls = [call for call in execute_calls if "DELETE FROM posthog_person_new" in call]
        assert len(delete_calls) == 150

    def test_scan_delete_chunk_serialization_failure_retry(self):
        """Test that serialization failure triggers retry."""
        config = DeletePersonsFromTriggerLogConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (0, 100)

        # Create IDs to delete - each needs id and team_id
        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_to_delete])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Track scan query attempts
        scan_attempts = [0]

        # First SELECT scan query raises SerializationFailure, second succeeds
        def execute_side_effect(query, *args):
            if "FROM posthog_person_deletes_log" in query:
                scan_attempts[0] += 1
                if scan_attempts[0] == 1:
                    # First scan attempt raises error
                    # Create a mock error with pgcode 40001 for serialization failure
                    error = create_mock_psycopg2_error("could not serialize access due to concurrent update", "40001")
                    raise error
                # Subsequent calls succeed - fetchall will return the IDs
            elif "DELETE FROM posthog_person_new" in query:
                # DELETE succeeds
                cursor.rowcount = 1
            # MagicMock will automatically record the call via side_effect

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Need to patch time.sleep and run.job_name
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with (
            patch("dags.delete_persons_from_trigger_log.time.sleep"),
            patch.object(type(context), "run", PropertyMock(return_value=mock_run)),
        ):
            scan_delete_chunk_for_dpft(context, config, chunk)

        # Verify ROLLBACK was called on error
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        assert "ROLLBACK" in execute_calls

        # Verify retry succeeded (should have SELECT called twice - once failed, once succeeded)
        scan_calls = [call for call in execute_calls if "FROM posthog_person_deletes_log" in call]
        assert len(scan_calls) >= 2  # At least one failed attempt and one successful scan

    def test_scan_delete_chunk_deadlock_retry(self):
        """Test that deadlock triggers retry."""
        config = DeletePersonsFromTriggerLogConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (0, 100)

        # Create IDs to delete - each needs id and team_id
        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_to_delete])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Track scan query attempts
        scan_attempts = [0]

        # First SELECT scan query raises deadlock, second succeeds
        def execute_side_effect(query, *args):
            if "FROM posthog_person_deletes_log" in query:
                scan_attempts[0] += 1
                if scan_attempts[0] == 1:
                    # First scan attempt raises error
                    # Create a mock error with pgcode 40P01 for deadlock
                    error = create_mock_psycopg2_error("deadlock detected", "40P01")
                    raise error
                # Subsequent calls succeed - fetchall will return the IDs
            elif "DELETE FROM posthog_person_new" in query:
                # DELETE succeeds
                cursor.rowcount = 1
            # MagicMock will automatically record the call via side_effect

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Need to patch time.sleep and run.job_name
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with (
            patch("dags.delete_persons_from_trigger_log.time.sleep"),
            patch.object(type(context), "run", PropertyMock(return_value=mock_run)),
        ):
            scan_delete_chunk_for_dpft(context, config, chunk)

        # Verify ROLLBACK was called on error
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        assert "ROLLBACK" in execute_calls

        # Verify retry succeeded (should have SELECT called twice - once failed, once succeeded)
        scan_calls = [call for call in execute_calls if "FROM posthog_person_deletes_log" in call]
        assert len(scan_calls) >= 2  # At least one failed attempt and one successful scan

    def test_scan_delete_chunk_error_handling_and_rollback(self):
        """Test error handling and rollback on non-retryable errors."""
        config = DeletePersonsFromTriggerLogConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (0, 100)

        # Create IDs to delete - each needs id and team_id
        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 51)]
        mock_db = create_mock_database_resource(fetchall_results=[ids_to_delete])
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Raise generic error on scan query (non-retryable error)
        def execute_side_effect(query, *args):
            if "FROM posthog_person_deletes_log" in query:
                raise Exception("Connection lost")
            # MagicMock will automatically record the call via side_effect

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_dpft
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with patch.object(type(context), "run", PropertyMock(return_value=mock_run)):
            # Should raise Dagster.Failure
            from dagster import Failure

            try:
                scan_delete_chunk_for_dpft(context, config, chunk)
                raise AssertionError("Expected Dagster.Failure to be raised")
            except Failure as e:
                # Verify error metadata
                assert e.description is not None
                assert "Failed to scan and delete rows in batch" in e.description

                # Verify ROLLBACK was called
                execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
                assert "ROLLBACK" in execute_calls

    def test_scan_delete_chunk_query_format(self):
        """Test that DELETE query has correct format."""
        config = DeletePersonsFromTriggerLogConfig(
            chunk_size=1000,
            batch_size=100,
        )
        chunk = (0, 100)

        # Create IDs to delete - each needs id and team_id
        ids_to_delete = [{"id": i, "team_id": 1} for i in range(1, 11)]  # 10 IDs
        mock_db = create_mock_database_resource(
            rowcount_values=1,  # Each DELETE deletes 1 person
            fetchall_results=[ids_to_delete],
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_dpft
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            scan_delete_chunk_for_dpft(context, config, chunk)

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Find DELETE query (should be multiple, one per person)
        delete_queries = [call for call in execute_calls if "DELETE FROM posthog_person_new" in call]
        assert len(delete_queries) == 10  # One delete per person

        # Verify DELETE query components (check first one)
        delete_query = delete_queries[0]
        assert "DELETE FROM posthog_person_new" in delete_query
        assert "WHERE team_id = %s AND id = %s" in delete_query

        # Find SELECT query (scan query)
        scan_query = next(
            (call for call in execute_calls if "FROM posthog_person_deletes_log" in call),
            None,
        )
        assert scan_query is not None

        # Verify SELECT query components
        assert "FROM posthog_person_deletes_log" in scan_query
        assert "ORDER BY pdl.id" in scan_query
        assert "LIMIT" in scan_query
        assert "OFFSET" in scan_query
        assert "EXISTS" in scan_query
        assert "SELECT" in scan_query

    def test_scan_delete_chunk_session_settings_applied_once(self):
        """Test that SET statements are applied once at session level before batch loop."""
        config = DeletePersonsFromTriggerLogConfig(
            chunk_size=1000,
            batch_size=50,
        )
        chunk = (0, 150)  # 3 scan batches

        # Create IDs to delete for each scan batch - each needs id and team_id
        fetchall_results = [
            [{"id": i, "team_id": 1} for i in range(1, 26)],  # 25 IDs from first scan batch
            [{"id": i, "team_id": 1} for i in range(51, 76)],  # 25 IDs from second scan batch
            [{"id": i, "team_id": 1} for i in range(101, 126)],  # 25 IDs from third scan batch
        ]
        mock_db = create_mock_database_resource(
            rowcount_values=1,  # Each DELETE deletes 1 person
            fetchall_results=fetchall_results,
        )
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in scan_delete_chunk_for_dpft
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            scan_delete_chunk_for_dpft(context, config, chunk)

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Count SET statements (should be called once each, before loop)
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
            assert max(set_indices) < min(begin_indices), "SET statements should come before BEGIN statements"


class TestGetScanRangeForDpft:
    """Test the get_scan_range_for_dpft function."""

    def test_get_scan_range_queries_row_count(self):
        """Test that database is queried for row count and converts to 0-indexed max_row."""
        config = DeletePersonsFromTriggerLogConfig()
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"row_count": 5000}

        context = build_op_context(resources={"database": mock_db})

        result = get_scan_range_for_dpft(context, config)

        # If COUNT(*) = 5000, rows are 0-indexed 0-4999, so max_row should be 4999
        assert result == (0, 4999)
        assert result[0] == 0  # min_row is always 0
        assert result[1] == 4999  # max_row is last 0-indexed row (row_count - 1)

        # Verify row count query was executed
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        row_count_queries = [
            call for call in execute_calls if "count(*)" in call.lower() and "posthog_person_deletes_log" in call
        ]
        assert len(row_count_queries) == 1, "Should query for row count from posthog_person_deletes_log"

    def test_get_scan_range_handles_zero_rows(self):
        """Test that zero rows returns (0, 0)."""
        config = DeletePersonsFromTriggerLogConfig()
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"row_count": 0}

        context = build_op_context(resources={"database": mock_db})

        result = get_scan_range_for_dpft(context, config)

        assert result == (0, 0)

    def test_get_scan_range_handles_none_row_count(self):
        """Test that None row count raises Failure."""
        config = DeletePersonsFromTriggerLogConfig()
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"row_count": None}

        context = build_op_context(resources={"database": mock_db})

        from dagster import Failure

        try:
            get_scan_range_for_dpft(context, config)
            raise AssertionError("Expected Dagster.Failure to be raised")
        except Failure as e:
            assert e.description is not None
            assert "no valid row count" in e.description.lower()

    def test_get_scan_range_handles_query_failure(self):
        """Test that query failures are properly handled when the row count query fails."""
        config = DeletePersonsFromTriggerLogConfig()
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        # Simulate query failure by raising an exception on execute
        cursor.execute.side_effect = Exception("Database connection lost")

        context = build_op_context(resources={"database": mock_db})

        try:
            get_scan_range_for_dpft(context, config)
            raise AssertionError("Expected exception to be raised")
        except Exception:
            # Query failure should bubble up
            assert True
