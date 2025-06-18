from posthog.helpers.batch_iterators import ArrayBatchIterator, FunctionBatchIterator
import pytest


class TestArrayBatchIterator:
    def test_array_batch_iterator(self):
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        expected_batches = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]
        batch_iterator = ArrayBatchIterator(data, batch_size=3)
        iteration_count = 0
        for batch_index, batch in batch_iterator:
            assert batch == expected_batches[iteration_count]
            assert batch_index == iteration_count
            iteration_count += 1
        assert iteration_count == len(expected_batches)

    def test_array_batch_iterator_empty(self):
        data = []
        batch_iterator = ArrayBatchIterator(data, batch_size=3)
        for _, _ in batch_iterator:
            raise AssertionError("Should not have any batches")
        assert True

    def test_array_batch_iterator_batch_size_bigger_than_data(self):
        data = [1, 2, 3]
        batch_iterator = ArrayBatchIterator(data, batch_size=4)
        for batch_index, batch in batch_iterator:
            assert batch == [1, 2, 3]
            assert batch_index == 0
        assert True


class TestFunctionBatchIterator:
    def test_function_batch_iterator_basic(self):
        # Test with a simple function that returns batches of numbers
        def create_batch(batch_index: int, batch_size: int) -> list[int]:
            start = batch_index * batch_size
            end = start + batch_size
            data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            return data[start:end] if start < len(data) else []

        expected_batches = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]
        batch_iterator = FunctionBatchIterator(create_batch, batch_size=3)

        iteration_count = 0
        for batch_index, batch in batch_iterator:
            assert batch == expected_batches[iteration_count]
            assert batch_index == iteration_count
            iteration_count += 1
        assert iteration_count == len(expected_batches)

    def test_function_batch_iterator_empty(self):
        def create_empty_batch(batch_index: int, batch_size: int) -> list[int]:
            return []

        batch_iterator = FunctionBatchIterator(create_empty_batch, batch_size=3)
        for _, _ in batch_iterator:
            raise AssertionError("Should not have any batches")
        assert True

    def test_function_batch_iterator_single_batch(self):
        def create_single_batch(batch_index: int, batch_size: int) -> list[int]:
            if batch_index == 0:
                return [1, 2, 3]
            return []

        batch_iterator = FunctionBatchIterator(create_single_batch, batch_size=3)
        batches = list(batch_iterator)
        assert len(batches) == 1
        assert batches[0] == (0, [1, 2, 3])

    def test_function_batch_iterator_variable_batch_sizes(self):
        def create_variable_batch(batch_index: int, batch_size: int) -> list[int]:
            if batch_index == 0:
                return [1, 2]  # Smaller than batch_size
            elif batch_index == 1:
                return [3, 4, 5, 6]  # Larger than batch_size
            elif batch_index == 2:
                return [7]  # Single item
            return []

        batch_iterator = FunctionBatchIterator(create_variable_batch, batch_size=3)
        batches = list(batch_iterator)
        assert len(batches) == 3
        assert batches[0] == (0, [1, 2])
        assert batches[1] == (1, [3, 4, 5, 6])
        assert batches[2] == (2, [7])

    def test_function_batch_iterator_with_early_termination(self):
        def create_batch_with_gaps(batch_index: int, batch_size: int) -> list[int]:
            if batch_index == 0:
                return [1, 2, 3]
            elif batch_index == 1:
                return []  # Empty batch should terminate
            elif batch_index == 2:
                return [4, 5, 6]  # This should never be reached

        batch_iterator = FunctionBatchIterator(create_batch_with_gaps, batch_size=3)
        batches = list(batch_iterator)
        assert len(batches) == 1
        assert batches[0] == (0, [1, 2, 3])

    def test_function_batch_iterator_batch_size_validation(self):
        def create_batch(batch_index: int, batch_size: int) -> list[int]:
            return [1, 2, 3]

        # Test that batch_size validation works
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            FunctionBatchIterator(create_batch, batch_size=0)

        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            FunctionBatchIterator(create_batch, batch_size=-1)


class TestBatchIterator:
    def test_batch_size_must_be_positive(self):
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            ArrayBatchIterator([1, 2, 3], batch_size=0)

        def create_batch(batch_index: int, batch_size: int) -> list[int]:
            return [1, 2, 3]

        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            FunctionBatchIterator(create_batch, batch_size=-5)
