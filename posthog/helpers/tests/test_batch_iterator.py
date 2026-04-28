import pytest

from posthog.helpers.batch_iterators import ArrayBatchIterator, CursorBatchIterator, FunctionBatchIterator


class TestArrayBatchIterator:
    def test_array_batch_iterator(self):
        data: list[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        expected_batches = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]
        batch_iterator = ArrayBatchIterator(data, batch_size=3)
        iteration_count = 0
        for batch_index, batch in batch_iterator:
            assert batch == expected_batches[iteration_count]
            assert batch_index == iteration_count
            iteration_count += 1
        assert iteration_count == len(expected_batches)

    def test_array_batch_iterator_empty(self):
        data: list[int] = []
        batch_iterator = ArrayBatchIterator(data, batch_size=3)
        for _, _ in batch_iterator:
            raise AssertionError("Should not have any batches")

    def test_array_batch_iterator_batch_size_bigger_than_data(self):
        data: list[int] = [1, 2, 3]
        batch_iterator = ArrayBatchIterator(data, batch_size=4)
        for batch_index, batch in batch_iterator:
            assert batch == [1, 2, 3]
            assert batch_index == 0


class TestFunctionBatchIterator:
    def test_function_batch_iterator_basic(self):
        # Test with a simple function that returns batches of numbers
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        def create_batch(batch_index: int, batch_size: int) -> list[int]:
            start = batch_index * batch_size
            end = start + batch_size
            return data[start:end] if start < len(data) else []

        expected_batches = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]
        batch_iterator = FunctionBatchIterator(create_batch, batch_size=3, max_items=10)

        iteration_count = 0
        for batch_index, batch in batch_iterator:
            assert batch == expected_batches[iteration_count]
            assert batch_index == iteration_count
            iteration_count += 1
        assert iteration_count == len(expected_batches)

    def test_function_batch_iterator_empty(self):
        def create_empty_batch(batch_index: int, batch_size: int) -> list[int]:
            return []

        batch_iterator = FunctionBatchIterator(create_empty_batch, batch_size=3, max_items=10)
        for _, _ in batch_iterator:
            raise AssertionError("Should not have any batches")
        return

    def test_function_batch_iterator_single_batch(self):
        data = [1, 2, 3]

        def create_single_batch(batch_index: int, batch_size: int) -> list[int]:
            return data

        batch_iterator = FunctionBatchIterator(create_single_batch, batch_size=3, max_items=3)
        batches = list(batch_iterator)
        assert len(batches) == 1
        assert batches[0] == (0, [1, 2, 3])

    def test_function_batch_iterator_with_early_termination(self):
        # Not a realistic case, but we should handle it
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        def create_batch_with_gaps(batch_index: int, batch_size: int) -> list[int]:
            start = batch_index * batch_size
            end = start + batch_size
            return data[start:end] if start < len(data) else []

        batch_iterator = FunctionBatchIterator(create_batch_with_gaps, batch_size=3, max_items=5)
        batches = list(batch_iterator)
        assert len(batches) == 2
        assert batches[0] == (0, [1, 2, 3])
        assert batches[1] == (1, [4, 5])

    def test_function_batch_iterator_batch_size_validation(self):
        def create_batch(batch_index: int, batch_size: int) -> list[int]:
            return [1, 2, 3]

        # Test that batch_size validation works
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            FunctionBatchIterator(create_batch, batch_size=0, max_items=10)

        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            FunctionBatchIterator(create_batch, batch_size=-1, max_items=10)

    def test_function_batch_iterator_skips_empty_batches(self):
        # Start with 10 items
        all_items = [1, 2, 3, 4, 6, 8, 9, 10, 11, 12]

        def create_batch_with_filtering(batch_index: int, batch_size: int) -> list[int]:
            start = batch_index * batch_size
            end = start + batch_size
            batch_items = all_items[start:end] if start < len(all_items) else []

            # Filter out even numbers (simulating some items being filtered out)
            return [item for item in batch_items if item % 2 == 1]

        batch_iterator = FunctionBatchIterator(create_batch_with_filtering, batch_size=3, max_items=10)
        batches = list(batch_iterator)
        assert len(batches) == 2  # Only 2 batches because empty batches are skipped
        assert batches[0] == (0, [1, 3])  # [1, 2, 3] filtered to [1, 3]
        # [4, 6, 8] filtered to [] so skipped
        assert batches[1] == (2, [9, 11])  # [9, 10, 11] filtered to [9, 11]
        # [12] filtered to [] so skipped


class TestCursorBatchIterator:
    def test_cursor_batch_iterator_basic(self):
        # Simulate paginating through a sorted list using cursor = last item value
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        def fetch_page(cursor: int, batch_size: int) -> tuple[list[int], int]:
            # cursor is the value after which to start
            remaining = [x for x in data if x > cursor]
            batch = remaining[:batch_size]
            next_cursor = batch[-1] if batch else cursor
            return batch, next_cursor

        batch_iterator = CursorBatchIterator(fetch_page, batch_size=3, initial_cursor=0)
        expected_batches = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]

        iteration_count = 0
        for batch_index, batch in batch_iterator:
            assert batch == expected_batches[iteration_count]
            assert batch_index == iteration_count
            iteration_count += 1
        assert iteration_count == len(expected_batches)

    def test_cursor_batch_iterator_empty(self):
        def fetch_page(cursor: int, batch_size: int) -> tuple[list[int], int]:
            return [], cursor

        batch_iterator = CursorBatchIterator(fetch_page, batch_size=3, initial_cursor=0)
        for _, _ in batch_iterator:
            raise AssertionError("Should not have any batches")

    def test_cursor_batch_iterator_single_batch(self):
        call_count = 0

        def fetch_page(cursor: int, batch_size: int) -> tuple[list[int], int]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [1, 2, 3], 3
            return [], 3

        batch_iterator = CursorBatchIterator(fetch_page, batch_size=3, initial_cursor=0)
        batches = list(batch_iterator)
        assert len(batches) == 1
        assert batches[0] == (0, [1, 2, 3])

    def test_cursor_batch_iterator_batch_size_validation(self):
        def fetch_page(cursor: int, batch_size: int) -> tuple[list[int], int]:
            return [1, 2, 3], 3

        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            CursorBatchIterator(fetch_page, batch_size=0, initial_cursor=0)

        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            CursorBatchIterator(fetch_page, batch_size=-1, initial_cursor=0)

    def test_cursor_batch_iterator_uneven_last_batch(self):
        # 10 items with batch_size=3, last batch should have 1 item
        data = list(range(1, 11))

        def fetch_page(cursor: int, batch_size: int) -> tuple[list[int], int]:
            remaining = [x for x in data if x > cursor]
            batch = remaining[:batch_size]
            next_cursor = batch[-1] if batch else cursor
            return batch, next_cursor

        batch_iterator = CursorBatchIterator(fetch_page, batch_size=3, initial_cursor=0)
        batches = list(batch_iterator)
        assert len(batches) == 4
        assert batches[0] == (0, [1, 2, 3])
        assert batches[1] == (1, [4, 5, 6])
        assert batches[2] == (2, [7, 8, 9])
        assert batches[3] == (3, [10])
        assert len(batches[-1][1]) == 1


class TestBatchIterator:
    def test_batch_size_must_be_positive(self):
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            ArrayBatchIterator([1, 2, 3], batch_size=0)

        def create_batch(batch_index: int, batch_size: int) -> list[int]:
            return [1, 2, 3]

        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            FunctionBatchIterator(create_batch, batch_size=-5, max_items=10)
