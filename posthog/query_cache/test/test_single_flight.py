import uuid
from datetime import UTC, datetime

from unittest import mock

from django.test import SimpleTestCase

from posthog.query_cache import single_flight, storage
from posthog.query_cache.failures import BUDGET_EXTENDED, BUDGET_INTERACTIVE
from posthog.query_cache.single_flight import FlightWait, QuerySingleFlight


def _cache_key() -> str:
    return f"test_{uuid.uuid4().hex}"


class TestQuerySingleFlight(SimpleTestCase):
    def test_only_one_leader_until_release(self):
        key = _cache_key()
        leader = QuerySingleFlight(key)
        assert leader.acquire(budget=BUDGET_INTERACTIVE) is True
        assert QuerySingleFlight(key).acquire(budget=BUDGET_INTERACTIVE) is False
        assert QuerySingleFlight(_cache_key()).acquire(budget=BUDGET_INTERACTIVE) is True

        leader.release()
        assert QuerySingleFlight(key).acquire(budget=BUDGET_INTERACTIVE) is True

    def test_release_keeps_a_replacement_leaders_lock(self):
        key = _cache_key()
        expired_leader = QuerySingleFlight(key)
        assert expired_leader.acquire(budget=BUDGET_INTERACTIVE) is True
        storage.query_cache_raw_client().delete(expired_leader.lock_key)  # the TTL ran out mid-query
        replacement_leader = QuerySingleFlight(key)
        assert replacement_leader.acquire(budget=BUDGET_INTERACTIVE) is True

        expired_leader.release(last_refresh=datetime(2026, 1, 1, tzinfo=UTC))
        assert QuerySingleFlight(key).acquire(budget=BUDGET_INTERACTIVE) is False  # the replacement still holds it
        assert QuerySingleFlight(key).wait(timeout_seconds=0) == FlightWait(outcome="timeout")  # and published nothing

    def test_heartbeat_extends_only_the_leaders_own_lock(self):
        key = _cache_key()
        leader = QuerySingleFlight(key)
        leader.acquire(budget=BUDGET_INTERACTIVE)
        client = storage.query_cache_raw_client()
        client.pexpire(leader.lock_key, 1)  # about to expire, as if the leader had gone quiet
        assert leader.extend() is True
        assert client.pttl(leader.lock_key) > 1000

        client.delete(leader.lock_key)
        replacement = QuerySingleFlight(key)
        replacement.acquire(budget=BUDGET_INTERACTIVE)
        client.pexpire(replacement.lock_key, 500)
        assert leader.extend() is False  # not the owner any more
        assert client.pttl(replacement.lock_key) <= 500

    def test_a_dead_leaders_lock_expires_and_followers_get_released(self):
        key = _cache_key()
        with mock.patch.object(single_flight, "FLIGHT_LOCK_TTL", 0.05):
            leader = QuerySingleFlight(key)
            leader.acquire(budget=BUDGET_INTERACTIVE)
            leader._heartbeat.stop()  # the process died: no more heartbeats, no release
        with mock.patch.object(single_flight, "FLIGHT_POLL_INTERVAL", 0.01):
            assert QuerySingleFlight(key).wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_acquire_drops_the_previous_flights_published_result(self):
        key = _cache_key()
        first_leader = QuerySingleFlight(key)
        first_leader.acquire(budget=BUDGET_INTERACTIVE)
        first_leader.release(last_refresh=datetime(2026, 1, 1, tzinfo=UTC))

        second_leader = QuerySingleFlight(key)
        assert second_leader.acquire(budget=BUDGET_INTERACTIVE) is True
        second_leader.release()  # failed without a result

        assert QuerySingleFlight(key).wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_released_with_a_result_tells_followers_which_entry_to_serve(self):
        key = _cache_key()
        leader = QuerySingleFlight(key)
        leader.acquire(budget=BUDGET_INTERACTIVE)
        written_at = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
        leader.release(last_refresh=written_at)

        assert QuerySingleFlight(key).wait(timeout_seconds=1) == FlightWait(outcome="done", last_refresh=written_at)
        assert QuerySingleFlight(key).acquire(budget=BUDGET_INTERACTIVE) is True  # the result does not hold the lock

    def test_released_without_a_result_tells_followers_to_run_it_themselves(self):
        key = _cache_key()
        leader = QuerySingleFlight(key)
        leader.acquire(budget=BUDGET_INTERACTIVE)
        leader.release()

        assert QuerySingleFlight(key).wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_followers_can_read_the_leaders_budget(self):
        key = _cache_key()
        assert QuerySingleFlight(key).leader_budget() is None
        leader = QuerySingleFlight(key)
        leader.acquire(budget=BUDGET_EXTENDED)
        assert QuerySingleFlight(key).leader_budget() == BUDGET_EXTENDED

        leader.release()
        assert QuerySingleFlight(key).leader_budget() is None

    def test_wait_times_out_while_leader_holds_the_lock(self):
        key = _cache_key()
        leader = QuerySingleFlight(key)
        leader.acquire(budget=BUDGET_INTERACTIVE)
        with mock.patch.object(single_flight, "FLIGHT_POLL_INTERVAL", 0.01):
            assert QuerySingleFlight(key).wait(timeout_seconds=0.05) == FlightWait(outcome="timeout")
        leader.release()

    def test_malformed_published_result_reads_as_released(self):
        flight = QuerySingleFlight(_cache_key())
        storage.query_cache_raw_client().set(flight.result_key, "not a timestamp")

        assert flight.wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_storage_errors_fail_open(self):
        flight = QuerySingleFlight(_cache_key())
        with mock.patch.object(single_flight.storage, "query_cache_raw_client", side_effect=RuntimeError("redis down")):
            assert flight.acquire(budget=BUDGET_INTERACTIVE) is True  # act alone rather than block the query
            assert flight.extend() is False
            assert flight.leader_budget() is None
            assert flight.wait(timeout_seconds=1) == FlightWait(outcome="released")  # run it yourself
            flight.release(last_refresh=datetime(2026, 1, 1, tzinfo=UTC))  # swallowed
