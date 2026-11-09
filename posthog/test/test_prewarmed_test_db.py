import io
import sys
import fcntl
import threading
from pathlib import Path
from typing import IO

import pytest

from posthog.test.prewarmed_test_db import DEVBOX_ENV_MARKERS, PREWARM_RUN_ENV, hold_test_db_lock


class _SignallingStream(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.written = threading.Event()

    def write(self, text: str) -> int:
        self.written.set()
        return super().write(text)


def _build_can_start(lock_path: Path) -> bool:
    with lock_path.open("a") as build:
        try:
            fcntl.flock(build, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


@pytest.fixture(autouse=True)
def _plain_test_run_on_a_devbox(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (PREWARM_RUN_ENV, "PYTEST_XDIST_WORKER", *DEVBOX_ENV_MARKERS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CODER", "true")


@pytest.mark.parametrize(
    "env, waits",
    [
        pytest.param({}, True, id="a-test-run-waits-for-the-build"),
        pytest.param({PREWARM_RUN_ENV: "1"}, False, id="the-build-does-not-wait-for-its-own-lock"),
        pytest.param({"PYTEST_XDIST_WORKER": "gw0"}, False, id="an-xdist-worker-uses-its-own-database"),
        pytest.param({"CODER": None}, False, id="a-machine-that-is-not-a-devbox-runs-no-build"),
    ],
)
def test_waits_only_while_the_prewarm_holds_its_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str | None], waits: bool
) -> None:
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name)
        else:
            monkeypatch.setenv(name, value)
    stderr = _SignallingStream()
    monkeypatch.setattr(sys, "stderr", stderr)
    lock_path = tmp_path / "test-db-prewarm.lock"
    held: list[IO[str] | None] = []
    with lock_path.open("w") as prewarm:
        fcntl.flock(prewarm, fcntl.LOCK_EX)
        waiter = threading.Thread(target=lambda: held.append(hold_test_db_lock(lock_path)), daemon=True)
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
    assert (held[0] is not None) == waits
    if held[0] is not None:
        held[0].close()


def test_a_running_test_keeps_a_later_build_out_until_it_ends(tmp_path: Path) -> None:
    lock_path = tmp_path / "not-yet-created" / "test-db-prewarm.lock"

    test_run = hold_test_db_lock(lock_path)

    assert test_run is not None
    assert not _build_can_start(lock_path)
    test_run.close()
    assert _build_can_start(lock_path)
