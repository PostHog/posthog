import sys
import asyncio
import threading
from typing import Protocol

# A fresh test org/team owns no person, cohort, or group rows, so its cascade
# delete is sub-second. A teardown delete that runs longer than this is wedged on
# an uncancellable backend call — historically a personhog gRPC delete that blocks
# the sync_to_async worker thread, which asyncio cannot cancel. When that happens
# the product-test shard burns its wall-clock cap and is cancelled, blocking
# unrelated PRs and the deploy gate. Bounding the call trades a leaked row
# (harmless: randomized names, reused/rebuilt test DB) for a session that always
# makes progress.
DEFAULT_TEARDOWN_DELETE_TIMEOUT_SECONDS = 10.0


class SupportsDelete(Protocol):
    def delete(self) -> object: ...


async def adelete_best_effort(
    instance: SupportsDelete, *, timeout: float = DEFAULT_TEARDOWN_DELETE_TIMEOUT_SECONDS
) -> bool:
    """Delete a model instance during async fixture teardown without letting a hung
    backend call wedge the test session.

    The delete runs on a daemon thread. If it finishes within ``timeout`` the outcome
    matches a direct ``instance.delete()`` (success, or a propagated error). If it does
    not, we abandon the thread and return ``False``: daemon threads do not block
    interpreter exit, so a leaked one is harmless — unlike asgiref's ``sync_to_async``
    pool, whose non-daemon workers would still hang the process on exit even after
    ``asyncio.wait_for`` gave up on the awaiting coroutine.

    Returns ``True`` if the delete completed, ``False`` if it was abandoned.
    """
    finished = threading.Event()
    error: list[Exception] = []

    def _delete() -> None:
        try:
            instance.delete()
        except Exception as exc:
            error.append(exc)
        finally:
            finished.set()

    threading.Thread(target=_delete, name=f"teardown-delete-{type(instance).__name__}", daemon=True).start()

    completed = await asyncio.get_running_loop().run_in_executor(None, finished.wait, timeout)
    if not completed:
        sys.stderr.write(
            f"abandoned hung {type(instance).__name__}.delete() teardown after {timeout}s (uncancellable backend call)\n"
        )
        return False
    if error:
        raise error[0]
    return True
