import time
from contextlib import contextmanager


@contextmanager
def assert_faster_than(duration_ms: float):
    start = time.monotonic()
    yield
    actual_duration = (time.monotonic() - start) * 1000.0
    assert actual_duration < duration_ms, (
        f"Execution took {actual_duration}ms which was not faster than {duration_ms}ms"
    )
