from unittest import mock

from django.core.cache import caches
from django.test import SimpleTestCase

from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS
from posthog.query_cache import single_flight
from posthog.query_cache.single_flight import FlightFailure, QuerySingleFlight


class TestQuerySingleFlight(SimpleTestCase):
    def setUp(self):
        super().setUp()
        caches[QUERY_CACHE_ALIAS].clear()

    def test_only_one_leader_until_release(self):
        flight = QuerySingleFlight("cache_key_1")
        assert flight.acquire() is True
        assert QuerySingleFlight("cache_key_1").acquire() is False
        assert QuerySingleFlight("cache_key_other").acquire() is True

        flight.release()
        assert QuerySingleFlight("cache_key_1").acquire() is True

    def test_failure_envelope_round_trips(self):
        flight = QuerySingleFlight("cache_key_2")
        assert flight.get_failure() is None
        flight.record_failure(FlightFailure(status_code=504, code="clickhouse_query_timeout", detail="timed out"))
        assert flight.get_failure() == FlightFailure(
            status_code=504, code="clickhouse_query_timeout", detail="timed out"
        )

    def test_wait_returns_failure_before_release(self):
        flight = QuerySingleFlight("cache_key_3")
        assert flight.acquire()
        flight.record_failure(FlightFailure(status_code=513, code="memory", detail="oom"))
        outcome = QuerySingleFlight("cache_key_3").wait(timeout_seconds=1)
        assert isinstance(outcome, FlightFailure)
        assert outcome.status_code == 513

    def test_wait_returns_released_when_no_leader(self):
        assert QuerySingleFlight("cache_key_4").wait(timeout_seconds=1) == "released"

    def test_wait_times_out_while_leader_holds_the_lock(self):
        QuerySingleFlight("cache_key_5").acquire()
        with mock.patch.object(single_flight, "FLIGHT_POLL_INTERVAL", 0.01):
            assert QuerySingleFlight("cache_key_5").wait(timeout_seconds=0.05) == "timeout"

    def test_storage_errors_fail_open(self):
        flight = QuerySingleFlight("cache_key_6")
        broken = mock.MagicMock()
        broken.__getitem__.side_effect = RuntimeError("redis down")
        with mock.patch.object(single_flight, "caches", broken):
            assert flight.acquire() is True  # act alone rather than block the query
            assert flight.in_flight() is False
            assert flight.get_failure() is None
            flight.record_failure(FlightFailure(status_code=504, code="x", detail="y"))  # swallowed
            flight.release()  # swallowed
