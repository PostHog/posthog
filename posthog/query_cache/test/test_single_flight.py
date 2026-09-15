from datetime import UTC, datetime

from unittest import mock

from django.test import SimpleTestCase

from posthog.query_cache import single_flight, storage
from posthog.query_cache.single_flight import FlightWait, QuerySingleFlight


class TestQuerySingleFlight(SimpleTestCase):
    def setUp(self):
        super().setUp()
        storage.query_cache_raw_client().flushdb()

    def test_only_one_leader_until_release(self):
        flight = QuerySingleFlight("cache_key_1")
        assert flight.acquire() is True
        assert QuerySingleFlight("cache_key_1").acquire() is False
        assert QuerySingleFlight("cache_key_other").acquire() is True

        flight.release()
        assert QuerySingleFlight("cache_key_1").acquire() is True

    def test_release_keeps_a_replacement_leaders_lock(self):
        expired_leader = QuerySingleFlight("cache_key_2")
        assert expired_leader.acquire() is True
        storage.query_cache_raw_client().delete(expired_leader.lock_key)  # the TTL ran out mid-query
        replacement_leader = QuerySingleFlight("cache_key_2")
        assert replacement_leader.acquire() is True

        expired_leader.release(last_refresh=datetime(2026, 1, 1, tzinfo=UTC))
        assert QuerySingleFlight("cache_key_2").acquire() is False  # the replacement still holds it
        assert replacement_leader.wait(timeout_seconds=0) == FlightWait(outcome="timeout")  # and published nothing

    def test_released_with_a_result_tells_followers_which_entry_to_serve(self):
        leader = QuerySingleFlight("cache_key_3")
        leader.acquire()
        written_at = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
        leader.release(last_refresh=written_at)

        assert QuerySingleFlight("cache_key_3").wait(timeout_seconds=1) == FlightWait(
            outcome="done", last_refresh=written_at
        )
        assert QuerySingleFlight("cache_key_3").acquire() is True  # the published result does not hold the lock

    def test_released_without_a_result_tells_followers_to_run_it_themselves(self):
        leader = QuerySingleFlight("cache_key_4")
        leader.acquire()
        leader.release()

        assert QuerySingleFlight("cache_key_4").wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_wait_times_out_while_leader_holds_the_lock(self):
        QuerySingleFlight("cache_key_5").acquire()
        with mock.patch.object(single_flight, "FLIGHT_POLL_INTERVAL", 0.01):
            assert QuerySingleFlight("cache_key_5").wait(timeout_seconds=0.05) == FlightWait(outcome="timeout")

    def test_storage_errors_fail_open(self):
        flight = QuerySingleFlight("cache_key_6")
        with mock.patch.object(single_flight.storage, "query_cache_raw_client", side_effect=RuntimeError("redis down")):
            assert flight.acquire() is True  # act alone rather than block the query
            assert flight.wait(timeout_seconds=1) == FlightWait(outcome="released")  # run it yourself
            flight.release(last_refresh=datetime(2026, 1, 1, tzinfo=UTC))  # swallowed
