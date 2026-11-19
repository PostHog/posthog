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
        # nosemgrep: no-fixed-sleeps-in-tests -- bounded polling for APIs without a readiness signal
        time.sleep(interval)
