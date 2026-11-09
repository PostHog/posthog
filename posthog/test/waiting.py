import time
from collections.abc import Callable


def wait_until(
    condition: Callable[[], bool],
    *,
    timeout: float = 5.0,
    interval: float = 0.01,
    message: str = "the condition never became true",
) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            raise AssertionError(f"{message} within {timeout}s")
        time.sleep(interval)  # noqa: TID251  # Polling must yield to the worker that changes the condition.
