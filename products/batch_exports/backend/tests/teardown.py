import asyncio
import threading
from collections.abc import Callable

from django.db import close_old_connections

import structlog

logger = structlog.get_logger(__name__)

# A fresh test org/team owns no person, cohort, or group rows, so its cascade
# delete is sub-second. A teardown call that runs longer than this is wedged on
# an uncancellable backend call — historically a personhog gRPC delete that
# blocks the worker thread, which asyncio cannot cancel. When that happens the
# product-test shard burns its wall-clock cap and is cancelled, blocking
# unrelated PRs and the deploy gate. Bounding the call lets the session keep
# making progress; that one teardown's rows are left behind, which is harmless
# because fixture names are randomized so leaked rows never collide with a later
# test (note: --reuse-db keeps the DB across runs, so they are not auto-cleared).
DEFAULT_TEARDOWN_TIMEOUT_SECONDS = 10.0


async def arun_best_effort(
    fn: Callable[[], object], *, label: str, timeout: float = DEFAULT_TEARDOWN_TIMEOUT_SECONDS
) -> bool:
    """Run a blocking teardown call on a daemon thread, bounded by ``timeout``.

    If ``fn`` finishes within ``timeout`` the outcome matches calling it directly
    (success, or a propagated exception). If it does not, we abandon the thread
    and return ``False``: daemon threads do not block interpreter exit, so a
    leaked one is harmless — unlike asgiref's ``sync_to_async`` pool, whose
    non-daemon workers would still hang the process on exit even after
    ``asyncio.wait_for`` gave up on the awaiting coroutine.

    Returns ``True`` if the call completed, ``False`` if it was abandoned.
    """
    finished = threading.Event()
    captured: Exception | None = None

    def _run() -> None:
        nonlocal captured
        try:
            fn()
        except Exception as exc:
            captured = exc
        finally:
            # This thread opened its own thread-local Django connection; with
            # CONN_MAX_AGE=0 and no request cycle to reap it, close it here so
            # teardowns don't leak connections toward Postgres max_connections.
            # (On the abandoned path the thread is stuck in fn() and never gets
            # here — that single leaked connection is the cost of the timeout.)
            close_old_connections()
            finished.set()

    threading.Thread(target=_run, name=f"teardown-{label}", daemon=True).start()

    completed = await asyncio.get_running_loop().run_in_executor(None, finished.wait, timeout)
    if not completed:
        logger.warning("teardown_call_abandoned", label=label, timeout_seconds=timeout)
        return False
    if captured is not None:
        raise captured
    return True
