import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def call_with_deadline(fn: Callable[[], T], seconds: float) -> T:
    """Return what `fn` returns, or raise `TimeoutError` when it runs longer than `seconds`.

    A read timeout restarts on every byte, and a streamed read blocks until its whole chunk arrives, so a
    server that trickles data keeps a download alive forever. Only a wall-clock deadline bounds it. `fn`
    runs in a daemon thread, so an abandoned call does not keep the interpreter alive at exit.
    """
    results: list[T] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            results.append(fn())
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if errors:
        raise errors[0]
    if not results:
        raise TimeoutError(f"no result after {seconds}s")
    return results[0]
