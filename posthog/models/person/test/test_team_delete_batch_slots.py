from django.test import SimpleTestCase

from posthog import redis
from posthog.models.person.team_delete_batch_slots import (
    QUEUE_KEY,
    SLOT_TTL_SECONDS,
    SLOTS_KEY,
    WAITERS_KEY,
    BatchSlotWaitTimeout,
    TeamDeletePersonsBatchSlots,
)
from posthog.test.waiting import wait_until


def _clear_batch_slots() -> None:
    redis.get_client().delete(SLOTS_KEY, QUEUE_KEY, WAITERS_KEY)


def _fail_on_wait(seconds: float) -> None:
    raise AssertionError("acquire waited for a slot")


class TestTeamDeletePersonsBatchSlots(SimpleTestCase):
    def setUp(self) -> None:
        _clear_batch_slots()
        self.addCleanup(_clear_batch_slots)

    def test_released_slot_goes_to_the_caller_that_waited_first(self) -> None:
        holder = TeamDeletePersonsBatchSlots(max_concurrent=lambda: 1)
        held = holder.acquire()
        assert held is not None
        holder_retries: list[str | None] = []

        def holder_releases_and_asks_again(seconds: float) -> None:
            if holder_retries:
                raise AssertionError("the released slot did not go to the waiter")
            holder.release(held)
            holder_retries.append(holder.acquire(should_stop=lambda: True))

        waiter = TeamDeletePersonsBatchSlots(max_concurrent=lambda: 1, sleep=holder_releases_and_asks_again)

        assert waiter.acquire() is not None
        assert holder_retries == [None]

    def test_expired_slot_frees_its_place(self) -> None:
        start = 1_000.0
        TeamDeletePersonsBatchSlots(max_concurrent=lambda: 1, clock=lambda: start).acquire()
        after_expiry = start + SLOT_TTL_SECONDS + 1

        waiter = TeamDeletePersonsBatchSlots(max_concurrent=lambda: 1, clock=lambda: after_expiry, sleep=_fail_on_wait)

        assert waiter.acquire() is not None

    def test_held_slot_stays_taken_past_its_ttl(self) -> None:
        now = [1_000.0]
        holder = TeamDeletePersonsBatchSlots(max_concurrent=lambda: 1, clock=lambda: now[0], renew_seconds=0.01)
        slot_id = holder.acquire()
        assert slot_id is not None

        with holder.hold(slot_id):
            now[0] += SLOT_TTL_SECONDS + 1
            wait_until(lambda: (redis.get_client().zscore(SLOTS_KEY, slot_id) or 0) > now[0])
            waiter = TeamDeletePersonsBatchSlots(max_concurrent=lambda: 1, clock=lambda: now[0])

            assert waiter.acquire(should_stop=lambda: True) is None

    def test_gives_up_after_the_wait_limit(self) -> None:
        now = [1_000.0]
        polls: list[float] = []

        def advance_clock(seconds: float) -> None:
            if len(polls) > 100:
                raise AssertionError("acquire kept waiting past its wait limit")
            polls.append(seconds)
            now[0] += seconds

        waiter = TeamDeletePersonsBatchSlots(
            max_concurrent=lambda: 0, clock=lambda: now[0], sleep=advance_clock, max_wait_seconds=1
        )

        with self.assertRaises(BatchSlotWaitTimeout):
            waiter.acquire()
        assert redis.get_client().zcard(QUEUE_KEY) == 0
