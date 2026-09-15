import contextvars
from collections.abc import Mapping
from typing import Any

from posthog.sync import database_sync_to_async


class UnComparableMapping(Mapping[str, Any]):
    # Stands in for a weak mapping that another thread mutates while `Mapping.__eq__` iterates it.
    def __iter__(self) -> Any:
        raise RuntimeError("dictionary changed size during iteration")

    def __getitem__(self, key: str) -> Any:
        raise KeyError(key)

    def __len__(self) -> int:
        return 0


uncomparable_var: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar("uncomparable_var")
propagated_var: contextvars.ContextVar[str] = contextvars.ContextVar("propagated_var")


async def test_returns_the_result_when_a_contextvar_value_cannot_be_compared() -> None:
    uncomparable_var.set(UnComparableMapping())

    result = await database_sync_to_async(lambda: "the result", thread_sensitive=False)()

    assert result == "the result"


async def test_a_contextvar_set_in_the_worker_thread_reaches_the_caller() -> None:
    def set_the_contextvar() -> None:
        propagated_var.set("set in the worker thread")

    await database_sync_to_async(set_the_contextvar, thread_sensitive=False)()

    assert propagated_var.get() == "set in the worker thread"
