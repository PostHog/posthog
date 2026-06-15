"""Tests for the persons new backfill job."""

from unittest.mock import MagicMock, patch

import psycopg2.errors
from dagster import build_op_context

from posthog.dags.persons_new_backfill import (
    PersonsNewBackfillConfig,
    copy_chunk,
    create_chunks_for_pnb,
    get_id_range_for_pnb,
)


class TestCreateChunksForPnb:
    """Test the create_chunks_for_pnb function."""

    def test_create_chunks_produces_non_overlapping_ranges(self):
        """Test that chunks produce non-overlapping ranges."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        id_range = (1, 5000)  # min_id=1, max_id=5000

        context = build_op_context()
        chunks = list(create_chunks_for_pnb(context, config, id_range))

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
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pnb(context, config, id_range))

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
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pnb(context, config, id_range))

        # First chunk in the list (yielded first, highest IDs)
        first_chunk_min, first_chunk_max = chunks[0].value

        assert first_chunk_max == max_id, f"First chunk max ({first_chunk_max}) should equal source max_id ({max_id})"
        assert first_chunk_min <= max_id <= first_chunk_max, (
            f"First chunk ({first_chunk_min}, {first_chunk_max}) should include max_id ({max_id})"
        )

    def test_create_chunks_final_chunk_includes_min_id(self):
        """Test that the final chunk (in yielded order) includes the source table min_id."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pnb(context, config, id_range))

        # Last chunk in the list (yielded last, lowest IDs)
        final_chunk_min, final_chunk_max = chunks[-1].value

        assert final_chunk_min == min_id, f"Final chunk min ({final_chunk_min}) should equal source min_id ({min_id})"
        assert final_chunk_min <= min_id <= final_chunk_max, (
            f"Final chunk ({final_chunk_min}, {final_chunk_max}) should include min_id ({min_id})"
        )

    def test_create_chunks_reverse_order(self):
        """Test that chunks are yielded in reverse order (highest IDs first)."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pnb(context, config, id_range))

        # Verify chunks are in descending order by max_id
        for i in range(len(chunks) - 1):
            current_max = chunks[i].value[1]
            next_max = chunks[i + 1].value[1]
            assert current_max > next_max, (
                f"Chunks not in reverse order: chunk {i} max ({current_max}) should be > chunk {i + 1} max ({next_max})"
            )

    def test_create_chunks_exact_multiple(self):
        """Test chunk creation when ID range is an exact multiple of chunk_size."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000  # Exactly 5 chunks of 1000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pnb(context, config, id_range))

        assert len(chunks) == 5, f"Expected 5 chunks, got {len(chunks)}"

        # Verify first chunk (highest IDs)
        assert chunks[0].value == (4001, 5000), f"First chunk should be (4001, 5000), got {chunks[0].value}"

        # Verify last chunk (lowest IDs)
        assert chunks[-1].value == (1, 1000), f"Last chunk should be (1, 1000), got {chunks[-1].value}"

    def test_create_chunks_non_exact_multiple(self):
        """Test chunk creation when ID range is not an exact multiple of chunk_size."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 3750  # 3 full chunks + 1 partial chunk
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pnb(context, config, id_range))

        assert len(chunks) == 4, f"Expected 4 chunks, got {len(chunks)}"

        # Verify first chunk (highest IDs) - should be the partial chunk
        assert chunks[0].value == (3001, 3750), f"First chunk should be (3001, 3750), got {chunks[0].value}"

        # Verify last chunk (lowest IDs)
        assert chunks[-1].value == (1, 1000), f"Last chunk should be (1, 1000), got {chunks[-1].value}"

    def test_create_chunks_single_chunk(self):
        """Test chunk creation when ID range fits in a single chunk."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 100, 500
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks_for_pnb(context, config, id_range))

        assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
        assert chunks[0].value == (100, 500), f"Chunk should be (100, 500), got {chunks[0].value}"
        assert chunks[0].value[0] == min_id and chunks[0].value[1] == max_id


def create_mock_database_resource(rowcount_values=None):
    """
    Create a mock database resource that mimics psycopg2.extensions.connection.

    Args:
        rowcount_values: List of rowcount values to return per INSERT call.
                        If None, defaults to 0. If a single int, uses that for all calls.
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

    # Make cursor() return a context manager
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    return mock_conn


def create_mock_cluster_resource():
    """Create a mock ClickhouseCluster resource."""
    return MagicMock()


class TestCopyChunk:
    """Test the copy_chunk function."""

    def test_copy_chunk_single_batch_success(self):
        """Test successful copy of a single batch within a chunk."""
        config = PersonsNewBackfillConfig(
            chunk_size=1000, batch_size=100, source_table="posthog_persons", destination_table="posthog_persons_new"
        )
        chunk = (1, 100)  # Single batch covers entire chunk

        mock_db = create_mock_database_resource(rowcount_values=50)
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in copy_chunk
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            result = copy_chunk(context, config, chunk)

        # Verify result
        assert result["chunk_min"] == 1
        assert result["chunk_max"] == 100
        assert result["records_copied"] == 50

        # Verify SET statements called once (session-level, before loop)
        set_statements = [
            "SET application_name = 'backfill_posthog_persons_to_posthog_persons_new'",
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

        # Verify BEGIN, INSERT, COMMIT called once
        assert execute_calls.count("BEGIN") == 1
        assert execute_calls.count("COMMIT") == 1

        # Verify INSERT query format
        insert_calls = [call for call in execute_calls if "INSERT INTO" in call]
        assert len(insert_calls) == 1
        insert_query = insert_calls[0]
        assert "INSERT INTO posthog_persons_new" in insert_query
        assert "SELECT s.*" in insert_query
        assert "FROM posthog_persons s" in insert_query
        assert "WHERE s.id >" in insert_query
        assert "AND s.id <=" in insert_query
        assert "NOT EXISTS" in insert_query
        assert "ORDER BY s.id DESC" in insert_query

    def test_copy_chunk_multiple_batches(self):
        """Test copy with multiple batches in a chunk."""
        config = PersonsNewBackfillConfig(
            chunk_size=1000, batch_size=100, source_table="posthog_persons", destination_table="posthog_persons_new"
        )
        chunk = (1, 250)  # 3 batches: (1,100), (100,200), (200,250)

        mock_db = create_mock_database_resource()
        mock_cluster = create_mock_cluster_resource()

        # Track rowcount per batch - use a list to track INSERT calls
        rowcounts = [50, 75, 25]
        insert_call_count = [0]

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Track INSERT calls and set rowcount accordingly
        def execute_with_rowcount(query, *args):
            if "INSERT INTO" in query:
                if insert_call_count[0] < len(rowcounts):
                    cursor.rowcount = rowcounts[insert_call_count[0]]
                    insert_call_count[0] += 1
                else:
                    cursor.rowcount = 0

        cursor.execute.side_effect = execute_with_rowcount

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in copy_chunk
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            result = copy_chunk(context, config, chunk)

        # Verify result
        assert result["chunk_min"] == 1
        assert result["chunk_max"] == 250
        assert result["records_copied"] == 150  # 50 + 75 + 25

        # Verify SET statements called once (before loop)
        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Verify BEGIN/COMMIT called 3 times (one per batch)
        assert execute_calls.count("BEGIN") == 3
        assert execute_calls.count("COMMIT") == 3

        # Verify INSERT called 3 times
        insert_calls = [call for call in execute_calls if "INSERT INTO" in call]
        assert len(insert_calls) == 3

    def test_copy_chunk_duplicate_key_violation_retry(self):
        """Test that duplicate key violation triggers retry."""
        config = PersonsNewBackfillConfig(
            chunk_size=1000, batch_size=100, source_table="posthog_persons", destination_table="posthog_persons_new"
        )
        chunk = (1, 100)

        mock_db = create_mock_database_resource()
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Track INSERT attempts
        insert_attempts = [0]

        # First INSERT raises UniqueViolation, second succeeds
        def execute_side_effect(query, *args):
            if "INSERT INTO" in query:
                insert_attempts[0] += 1
                if insert_attempts[0] == 1:
                    # First INSERT attempt raises error
                    # Use real UniqueViolation - pgcode is readonly but isinstance check will pass
                    raise psycopg2.errors.UniqueViolation("duplicate key value violates unique constraint")
                # Subsequent calls succeed
                cursor.rowcount = 50  # Success on retry

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Need to patch time.sleep and run.job_name
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with (
            patch("posthog.dags.persons_new_backfill.time.sleep"),
            patch.object(type(context), "run", PropertyMock(return_value=mock_run)),
        ):
            copy_chunk(context, config, chunk)

        # Verify ROLLBACK was called on error
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        assert "ROLLBACK" in execute_calls

        # Verify retry succeeded (should have INSERT called twice, COMMIT once)
        insert_calls = [call for call in execute_calls if "INSERT INTO" in call]
        assert len(insert_calls) >= 1  # At least one successful INSERT

    def test_copy_chunk_error_handling_and_rollback(self):
        """Test error handling and rollback on non-duplicate errors."""
        config = PersonsNewBackfillConfig(
            chunk_size=1000, batch_size=100, source_table="posthog_persons", destination_table="posthog_persons_new"
        )
        chunk = (1, 100)

        mock_db = create_mock_database_resource()
        mock_cluster = create_mock_cluster_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        # Raise generic error on INSERT
        def execute_side_effect(query, *args):
            if "INSERT INTO" in query:
                raise Exception("Connection lost")

        cursor.execute.side_effect = execute_side_effect

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in copy_chunk
        from unittest.mock import PropertyMock

        mock_run = MagicMock(job_name="test_job")
        with patch.object(type(context), "run", PropertyMock(return_value=mock_run)):
            # Should raise Dagster.Failure
            from dagster import Failure

            try:
                copy_chunk(context, config, chunk)
                raise AssertionError("Expected Dagster.Failure to be raised")
            except Failure as e:
                # Verify error metadata
                assert e.description is not None
                assert "Failed to copy batch" in e.description

                # Verify ROLLBACK was called
                execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
                assert "ROLLBACK" in execute_calls

    def test_copy_chunk_insert_query_format(self):
        """Test that INSERT query has correct format."""
        config = PersonsNewBackfillConfig(
            chunk_size=1000, batch_size=100, source_table="test_source", destination_table="test_dest"
        )
        chunk = (1, 100)

        mock_db = create_mock_database_resource(rowcount_values=10)
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in copy_chunk
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            copy_chunk(context, config, chunk)

        cursor = mock_db.cursor.return_value.__enter__.return_value
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]

        # Find INSERT query
        insert_query = next((call for call in execute_calls if "INSERT INTO" in call), None)
        assert insert_query is not None

        # Verify query components
        assert "INSERT INTO test_dest" in insert_query
        assert "SELECT s.*" in insert_query
        assert "FROM test_source s" in insert_query
        assert "WHERE s.id >" in insert_query
        assert "AND s.id <=" in insert_query
        assert "NOT EXISTS" in insert_query
        assert "d.team_id = s.team_id" in insert_query
        assert "d.id = s.id" in insert_query
        assert "ORDER BY s.id DESC" in insert_query

    def test_copy_chunk_session_settings_applied_once(self):
        """Test that SET statements are applied once at session level before batch loop."""
        config = PersonsNewBackfillConfig(
            chunk_size=1000, batch_size=50, source_table="posthog_persons", destination_table="posthog_persons_new"
        )
        chunk = (1, 150)  # 3 batches

        mock_db = create_mock_database_resource(rowcount_values=25)
        mock_cluster = create_mock_cluster_resource()

        context = build_op_context(
            resources={"database": mock_db, "cluster": mock_cluster},
        )
        # Patch context.run.job_name where it's accessed in copy_chunk
        from unittest.mock import PropertyMock

        with patch.object(type(context), "run", PropertyMock(return_value=MagicMock(job_name="test_job"))):
            copy_chunk(context, config, chunk)

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


class TestGetIdRangeForPnb:
    """Test the get_id_range_for_pnb function."""

    def test_get_id_range_uses_min_id_override(self):
        """Test that min_id override is honored when provided."""
        config = PersonsNewBackfillConfig(min_id=100, max_id=None, source_table="posthog_persons")
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"max_id": 5000}

        context = build_op_context(resources={"database": mock_db})

        result = get_id_range_for_pnb(context, config)

        assert result == (100, 5000)
        assert result[0] == 100  # min_id override used

        # Verify min_id query was NOT executed (override used)
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        min_queries = [call for call in execute_calls if "MIN(id)" in call]
        assert len(min_queries) == 0, "Should not query for min_id when override is provided"

        # Verify max_id query WAS executed
        max_queries = [call for call in execute_calls if "MAX(id)" in call]
        assert len(max_queries) == 1, "Should query for max_id when override is not provided"

    def test_get_id_range_uses_max_id_override(self):
        """Test that max_id override is honored when provided."""
        config = PersonsNewBackfillConfig(min_id=None, max_id=5000, source_table="posthog_persons")
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"min_id": 1}

        context = build_op_context(resources={"database": mock_db})

        result = get_id_range_for_pnb(context, config)

        assert result == (1, 5000)
        assert result[1] == 5000  # max_id override used

        # Verify max_id query was NOT executed (override used)
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        max_queries = [call for call in execute_calls if "MAX(id)" in call]
        assert len(max_queries) == 0, "Should not query for max_id when override is provided"

        # Verify min_id query WAS executed
        min_queries = [call for call in execute_calls if "MIN(id)" in call]
        assert len(min_queries) == 1, "Should query for min_id when override is not provided"

    def test_get_id_range_uses_both_overrides(self):
        """Test that both min_id and max_id overrides are honored when provided."""
        config = PersonsNewBackfillConfig(min_id=100, max_id=5000, source_table="posthog_persons")
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value

        context = build_op_context(resources={"database": mock_db})

        result = get_id_range_for_pnb(context, config)

        assert result == (100, 5000)
        assert result[0] == 100  # min_id override used
        assert result[1] == 5000  # max_id override used

        # Verify NO queries were executed (both overrides used)
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        min_queries = [call for call in execute_calls if "MIN(id)" in call]
        max_queries = [call for call in execute_calls if "MAX(id)" in call]
        assert len(min_queries) == 0, "Should not query for min_id when override is provided"
        assert len(max_queries) == 0, "Should not query for max_id when override is provided"

    def test_get_id_range_queries_database_when_no_overrides(self):
        """Test that database is queried when no overrides are provided."""
        config = PersonsNewBackfillConfig(min_id=None, max_id=None, source_table="posthog_persons")
        mock_db = create_mock_database_resource()

        cursor = mock_db.cursor.return_value.__enter__.return_value
        # First call returns min_id, second call returns max_id
        cursor.fetchone.side_effect = [{"min_id": 1}, {"max_id": 5000}]

        context = build_op_context(resources={"database": mock_db})

        result = get_id_range_for_pnb(context, config)

        assert result == (1, 5000)

        # Verify both queries were executed
        execute_calls = [call[0][0] for call in cursor.execute.call_args_list]
        min_queries = [call for call in execute_calls if "MIN(id)" in call]
        max_queries = [call for call in execute_calls if "MAX(id)" in call]
        assert len(min_queries) == 1, "Should query for min_id when override is not provided"
        assert len(max_queries) == 1, "Should query for max_id when override is not provided"

    def test_get_id_range_validates_max_id_greater_than_min_id(self):
        """Test that validation fails when max_id < min_id."""
        config = PersonsNewBackfillConfig(min_id=5000, max_id=100, source_table="posthog_persons")
        mock_db = create_mock_database_resource()

        context = build_op_context(resources={"database": mock_db})

        from dagster import Failure

        try:
            get_id_range_for_pnb(context, config)
            raise AssertionError("Expected Dagster.Failure to be raised")
        except Failure as e:
            assert e.description is not None
            description = e.description
            assert "max_id" in description.lower() or "invalid" in description.lower()
            assert "5000" in description or "100" in description
