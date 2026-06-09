import time
import threading

import pytest

from products.batch_exports.backend.tests.teardown import adelete_best_effort


class _FakeDeletable:
    def __init__(self, block: threading.Event | None = None, error: Exception | None = None) -> None:
        self._block = block
        self._error = error
        self.deleted = False

    def delete(self) -> None:
        if self._block is not None:
            self._block.wait()  # hang until released, simulating a wedged backend call
        if self._error is not None:
            raise self._error
        self.deleted = True


async def test_adelete_best_effort_completes_normally():
    obj = _FakeDeletable()

    assert await adelete_best_effort(obj, timeout=5) is True
    assert obj.deleted is True


async def test_adelete_best_effort_abandons_hung_delete():
    release = threading.Event()
    obj = _FakeDeletable(block=release)

    start = time.monotonic()
    try:
        completed = await adelete_best_effort(obj, timeout=0.2)
        elapsed = time.monotonic() - start

        assert completed is False
        assert elapsed < 2  # returned at the timeout instead of hanging on the blocked delete
    finally:
        release.set()  # unblock the daemon thread so it exits cleanly


async def test_adelete_best_effort_propagates_real_errors():
    obj = _FakeDeletable(error=ValueError("boom"))

    with pytest.raises(ValueError, match="boom"):
        await adelete_best_effort(obj, timeout=5)
