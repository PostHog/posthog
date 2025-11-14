"""Tests for the persons new backfill job."""

from dagster import build_op_context

from dags.persons_new_backfill import PersonsNewBackfillConfig, create_chunks


class TestCreateChunks:
    """Test the create_chunks function."""

    def test_create_chunks_produces_non_overlapping_ranges(self):
        """Test that chunks produce non-overlapping ranges."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        id_range = (1, 5000)  # min_id=1, max_id=5000

        context = build_op_context()
        chunks = list(create_chunks(context, config, id_range))

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

    def test_create_chunks_covers_entire_id_space(self):
        """Test that chunks cover the entire ID space from min to max."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks(context, config, id_range))

        # Extract all chunk ranges from DynamicOutput objects
        chunk_ranges = [chunk.value for chunk in chunks]

        # Find the overall min and max covered
        all_ids_covered = set()
        for chunk_min, chunk_max in chunk_ranges:
            all_ids_covered.update(range(chunk_min, chunk_max + 1))

        # Verify all IDs from min_id to max_id are covered
        expected_ids = set(range(min_id, max_id + 1))
        assert all_ids_covered == expected_ids, (
            f"Missing IDs: {expected_ids - all_ids_covered}, " f"Extra IDs: {all_ids_covered - expected_ids}"
        )

    def test_create_chunks_first_chunk_includes_max_id(self):
        """Test that the first chunk (in yielded order) includes the source table max_id."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks(context, config, id_range))

        # First chunk in the list (yielded first, highest IDs)
        first_chunk_min, first_chunk_max = chunks[0].value

        assert first_chunk_max == max_id, f"First chunk max ({first_chunk_max}) should equal source max_id ({max_id})"
        assert (
            first_chunk_min <= max_id <= first_chunk_max
        ), f"First chunk ({first_chunk_min}, {first_chunk_max}) should include max_id ({max_id})"

    def test_create_chunks_final_chunk_includes_min_id(self):
        """Test that the final chunk (in yielded order) includes the source table min_id."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks(context, config, id_range))

        # Last chunk in the list (yielded last, lowest IDs)
        final_chunk_min, final_chunk_max = chunks[-1].value

        assert final_chunk_min == min_id, f"Final chunk min ({final_chunk_min}) should equal source min_id ({min_id})"
        assert (
            final_chunk_min <= min_id <= final_chunk_max
        ), f"Final chunk ({final_chunk_min}, {final_chunk_max}) should include min_id ({min_id})"

    def test_create_chunks_reverse_order(self):
        """Test that chunks are yielded in reverse order (highest IDs first)."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks(context, config, id_range))

        # Verify chunks are in descending order by max_id
        for i in range(len(chunks) - 1):
            current_max = chunks[i].value[1]
            next_max = chunks[i + 1].value[1]
            assert (
                current_max > next_max
            ), f"Chunks not in reverse order: chunk {i} max ({current_max}) should be > chunk {i+1} max ({next_max})"

    def test_create_chunks_exact_multiple(self):
        """Test chunk creation when ID range is an exact multiple of chunk_size."""
        config = PersonsNewBackfillConfig(chunk_size=1000)
        min_id, max_id = 1, 5000  # Exactly 5 chunks of 1000
        id_range = (min_id, max_id)

        context = build_op_context()
        chunks = list(create_chunks(context, config, id_range))

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
        chunks = list(create_chunks(context, config, id_range))

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
        chunks = list(create_chunks(context, config, id_range))

        assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"
        assert chunks[0].value == (100, 500), f"Chunk should be (100, 500), got {chunks[0].value}"
        assert chunks[0].value[0] == min_id and chunks[0].value[1] == max_id
