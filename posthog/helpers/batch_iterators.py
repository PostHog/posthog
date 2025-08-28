from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import Generic, TypeVar

T = TypeVar("T")


class BatchIterator(ABC, Generic[T]):
    """
    Abstract base class for lazily yielding batches of data with their batch index.
    """

    def __init__(self, batch_size: int):
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.batch_size = batch_size

    @abstractmethod
    def __iter__(self) -> Iterator[tuple[int, list[T]]]: ...


class ArrayBatchIterator(BatchIterator[T]):
    """
    Batches an in-memory list into (batch_index, batch_data) pairs.
    """

    def __init__(self, data: list[T], batch_size: int):
        super().__init__(batch_size)
        self.data = data
        self._delegate = FunctionBatchIterator(self._batch_fn, batch_size, len(data))

    def _batch_fn(self, batch_index: int, batch_size: int) -> list[T]:
        start = batch_index * batch_size
        end = start + batch_size
        return self.data[start:end] if start < len(self.data) else []

    def __iter__(self):
        return iter(self._delegate)


class FunctionBatchIterator(BatchIterator[T]):
    """
    Lazily yields batches by calling a function that produces each batch.
    Useful for complex querying scenarios where each batch requires custom logic.

    The function should take (batch_index: int, batch_size: int) and return a list of items.
    The iterator will continue until max_items is reached, ignoring empty batches.
    """

    def __init__(self, batch_function: Callable[[int, int], list[T]], batch_size: int, max_items: int):
        super().__init__(batch_size)
        self.batch_function = batch_function
        self.max_items = max_items
        self.max_batches = (self.max_items + self.batch_size - 1) // self.batch_size

    def __iter__(self) -> Iterator[tuple[int, list[T]]]:
        for batch_index in range(self.max_batches):
            batch_data = self.batch_function(batch_index, self.batch_size)
            if batch_data:
                start_item = batch_index * self.batch_size
                end_item = start_item + len(batch_data)
                if end_item > self.max_items:
                    batch_data = batch_data[: self.max_items - start_item]
                yield batch_index, batch_data
