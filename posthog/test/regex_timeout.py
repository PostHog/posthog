from collections.abc import Callable
from multiprocessing import get_context


def assert_regex_completes(callback: Callable[[], None], timeout: float = 5.0) -> None:
    """Run pure matching assertions in a killable process, outside the test runner.

    Fork inherits already imported application code, keeping Django startup outside
    the deadline. The callback must not use database connections or other services.
    """
    process = get_context("fork").Process(target=callback)
    process.start()
    try:
        process.join(timeout)
        assert not process.is_alive(), f"Matching did not finish within {timeout} seconds"
        assert process.exitcode == 0, f"Matching assertions failed (exit code {process.exitcode})"
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        process.close()
