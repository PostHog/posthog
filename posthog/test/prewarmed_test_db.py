import os
import sys
import fcntl
from pathlib import Path
from typing import IO

# `hogli devbox:worktree` holds this lock while it builds the test database: see _TEST_DB_PREWARM_SCRIPT there.
PREWARM_LOCK = Path.home() / ".cache" / "hogli" / "test-db-prewarm.lock"
PREWARM_RUN_ENV = "HOGLI_TEST_DB_PREWARM"
DEVBOX_ENV_MARKERS = ("CODER", "CODER_WORKSPACE_NAME")


def hold_test_db_lock(lock_path: Path = PREWARM_LOCK) -> IO[str] | None:
    """Wait for a running build, then hold a shared lock until the caller closes the returned file.

    The build takes the lock exclusively without blocking, so it skips while any test run holds it.
    """
    # Only a devbox runs the build. Checking for the lock file instead would let a test that started before the
    # first build run alongside it.
    if not any(os.environ.get(marker) for marker in DEVBOX_ENV_MARKERS):
        return None
    # An xdist worker sets up its own suffixed databases, which the build does not touch.
    if os.environ.get(PREWARM_RUN_ENV) or os.environ.get("PYTEST_XDIST_WORKER"):
        return None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = lock_path.open("a")
    except OSError:
        return None
    try:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.stderr.write(
            "Waiting for the test database build that `hogli devbox:worktree` started. "
            f"Log: {lock_path.with_suffix('.log')}\n"
        )
        fcntl.flock(lock, fcntl.LOCK_SH)
    return lock
