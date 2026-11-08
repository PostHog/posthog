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
    "prewarm_env, waits",
    [
        pytest.param(None, True, id="a-test-run-waits-for-the-build"),
        pytest.param("1", False, id="the-build-does-not-wait-for-its-own-lock"),
    ],
)
def test_waits_only_while_the_prewarm_holds_its_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prewarm_env: str | None, waits: bool
) -> None:
    if prewarm_env is None:
        monkeypatch.delenv(PREWARM_RUN_ENV, raising=False)
    else:
        monkeypatch.setenv(PREWARM_RUN_ENV, prewarm_env)
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
