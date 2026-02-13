import threading

import pytest
from posthog.test.base import failhard_threadhook_context


@pytest.mark.xfail(strict=True, reason="verifies thread exceptions propagate as test failures")
def test_failhard_threadhook_propagates_thread_exceptions():
    with failhard_threadhook_context():
        thread = threading.Thread(target=_raise_value_error)
        thread.start()
        thread.join()


def _raise_value_error():
    raise ValueError("boom")
