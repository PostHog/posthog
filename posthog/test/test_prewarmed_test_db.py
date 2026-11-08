import io
import sys
import fcntl
import threading
from pathlib import Path

import pytest

from posthog.test.prewarmed_test_db import PREWARM_RUN_ENV, wait_for_test_db_prewarm


class _SignallingStream(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.written = threading.Event()

    def write(self, text: str) -> int:
        self.written.set()
        return super().write(text)


@pytest.mark.parametrize(
    "env, waits",
    [
        pytest.param({}, True, id="a-test-run-waits-for-the-build"),
        pytest.param({PREWARM_RUN_ENV: "1"}, False, id="the-build-does-not-wait-for-its-own-lock"),
        pytest.param({"PYTEST_XDIST_WORKER": "gw0"}, False, id="an-xdist-worker-uses-its-own-database"),
    ],
)
def test_waits_only_while_the_prewarm_holds_its_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], waits: bool
) -> None:
    for name in (PREWARM_RUN_ENV, "PYTEST_XDIST_WORKER"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    stderr = _SignallingStream()
    monkeypatch.setattr(sys, "stderr", stderr)
    lock_path = tmp_path / "test-db-prewarm.lock"
    with lock_path.open("w") as prewarm:
        fcntl.flock(prewarm, fcntl.LOCK_EX)
        waiter = threading.Thread(target=wait_for_test_db_prewarm, args=(lock_path,), daemon=True)
        waiter.start()
        if waits:
            assert stderr.written.wait(timeout=5)
            assert waiter.is_alive()
        else:
            waiter.join(timeout=5)
            assert not waiter.is_alive()
            assert not stderr.written.is_set()

        fcntl.flock(prewarm, fcntl.LOCK_UN)
        waiter.join(timeout=5)
        assert not waiter.is_alive()
