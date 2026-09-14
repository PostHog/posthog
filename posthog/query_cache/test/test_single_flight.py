from unittest import mock

from django.test import SimpleTestCase

from posthog.query_cache import single_flight, storage
from posthog.query_cache.single_flight import QuerySingleFlight


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

        expired_leader.release()
        assert QuerySingleFlight("cache_key_2").acquire() is False  # the replacement still holds it

    def test_wait_returns_released_when_no_leader(self):
        assert QuerySingleFlight("cache_key_3").wait(timeout_seconds=1) == "released"

    def test_wait_times_out_while_leader_holds_the_lock(self):
        QuerySingleFlight("cache_key_4").acquire()
        with mock.patch.object(single_flight, "FLIGHT_POLL_INTERVAL", 0.01):
            assert QuerySingleFlight("cache_key_4").wait(timeout_seconds=0.05) == "timeout"

    def test_storage_errors_fail_open(self):
        flight = QuerySingleFlight("cache_key_5")
        with mock.patch.object(single_flight.storage, "query_cache_raw_client", side_effect=RuntimeError("redis down")):
            assert flight.acquire() is True  # act alone rather than block the query
            assert flight.in_flight() is False
            flight.release()  # swallowed
