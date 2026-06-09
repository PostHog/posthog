import time
import random
import threading

import pytest

from asgiref.sync import sync_to_async

from posthog.models import Organization

from products.batch_exports.backend.tests.teardown import arun_best_effort


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


async def test_arun_best_effort_completes_normally():
    obj = _FakeDeletable()

    assert await arun_best_effort(obj.delete, label="fake") is True
    assert obj.deleted is True


async def test_arun_best_effort_abandons_hung_call():
    release = threading.Event()
    obj = _FakeDeletable(block=release)

    start = time.monotonic()
    try:
        completed = await arun_best_effort(obj.delete, label="fake", timeout=0.2)
        elapsed = time.monotonic() - start

        assert completed is False
        assert 0.2 <= elapsed < 2  # returned at the timeout bound, not before and not hung
    finally:
        release.set()  # unblock the daemon thread so it exits cleanly


async def test_arun_best_effort_propagates_real_errors():
    obj = _FakeDeletable(error=ValueError("boom"))

    with pytest.raises(ValueError, match="boom"):
        await arun_best_effort(obj.delete, label="fake")


async def test_arun_best_effort_deletes_a_real_model(db):
    # Guards the actual change: the delete runs on a different thread/connection
    # than the create, so prove it still removes a real committed row.
    org = await sync_to_async(Organization.objects.create)(
        name=f"TeardownTest-{random.randint(1, 99999)}", is_ai_data_processing_approved=True
    )

    assert await arun_best_effort(org.delete, label="organization") is True
    assert await sync_to_async(Organization.objects.filter(pk=org.pk).exists)() is False
