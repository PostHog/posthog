import uuid
from datetime import UTC, datetime

from unittest import mock

from django.test import SimpleTestCase

from posthog.query_cache import single_flight, storage
from posthog.query_cache.failures import BUDGET_EXTENDED, BUDGET_INTERACTIVE
from posthog.query_cache.single_flight import FlightWait, QuerySingleFlight, SharedFailure


def _cache_key() -> str:
    return f"test_{uuid.uuid4().hex}"


class TestQuerySingleFlight(SimpleTestCase):
    def test_only_one_leader_until_release(self):
        key = _cache_key()
        leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        assert leader.acquire() is True
        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).acquire() is False
        assert QuerySingleFlight(_cache_key(), BUDGET_INTERACTIVE).acquire() is True

        leader.release()
        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).acquire() is True

    def test_runs_of_different_budgets_lead_their_own_flights(self):
        key = _cache_key()
        interactive = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        extended = QuerySingleFlight(key, BUDGET_EXTENDED)
        self.addCleanup(interactive.release)
        self.addCleanup(extended.release)
        assert interactive.acquire() is True
        assert extended.acquire() is True

    def test_release_keeps_a_replacement_leaders_lock(self):
        key = _cache_key()
        expired_leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        assert expired_leader.acquire() is True
        storage.query_cache_raw_client().delete(expired_leader.lock_key)  # the TTL ran out mid-query
        replacement_leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        assert replacement_leader.acquire() is True

        expired_leader.succeed(datetime(2026, 1, 1, tzinfo=UTC))
        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).acquire() is False  # the replacement still holds it
        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).wait(timeout_seconds=0) == FlightWait(
            outcome="timeout"
        )  # and published nothing

    def test_heartbeat_extends_only_the_leaders_own_lock(self):
        key = _cache_key()
        leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        leader.acquire()
        client = storage.query_cache_raw_client()
        client.pexpire(leader.lock_key, 1)  # about to expire, as if the leader had gone quiet
        assert leader.extend() is True
        assert client.pttl(leader.lock_key) > 1000

        client.delete(leader.lock_key)
        replacement = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        replacement.acquire()
        client.pexpire(replacement.lock_key, 500)
        assert leader.extend() is False  # not the owner any more
        assert client.pttl(replacement.lock_key) <= 500

    def test_a_dead_leaders_lock_expires_and_followers_get_released(self):
        key = _cache_key()
        with mock.patch.object(single_flight, "FLIGHT_LOCK_TTL", 0.05):
            leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
            leader.acquire()
            assert leader._heartbeat is not None
            leader._heartbeat.stop()  # the process died: no more heartbeats, no release
        with mock.patch.object(single_flight, "FLIGHT_POLL_INTERVAL", 0.01):
            assert QuerySingleFlight(key, BUDGET_INTERACTIVE).wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_acquire_drops_the_previous_flights_published_result(self):
        key = _cache_key()
        first_leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        first_leader.acquire()
        first_leader.succeed(datetime(2026, 1, 1, tzinfo=UTC))

        second_leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        assert second_leader.acquire() is True
        second_leader.release()

        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_succeeded_tells_followers_which_entry_to_serve(self):
        key = _cache_key()
        leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        leader.acquire()
        written_at = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
        leader.succeed(written_at)

        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).wait(timeout_seconds=1) == FlightWait(
            outcome="done", last_refresh=written_at
        )
        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).acquire() is True  # the result does not hold the lock

    def test_released_without_a_publication_reads_as_released(self):
        key = _cache_key()
        leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        leader.acquire()
        leader.release()

        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_failed_with_a_shareable_failure_tells_followers_to_fail_the_same_way(self):
        key = _cache_key()
        leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        leader.acquire()
        failure = SharedFailure(message="Memory limit (for query) exceeded", code=241)
        leader.fail(failure)

        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).wait(timeout_seconds=1) == FlightWait(
            outcome="failed", failure=failure
        )
        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).acquire() is True  # the failure does not hold the lock

    def test_failed_without_a_shareable_failure_tells_followers_the_leader_failed(self):
        key = _cache_key()
        leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        leader.acquire()
        leader.fail(None)

        assert QuerySingleFlight(key, BUDGET_INTERACTIVE).wait(timeout_seconds=1) == FlightWait(outcome="failed")

    def test_wait_times_out_while_leader_holds_the_lock(self):
        key = _cache_key()
        leader = QuerySingleFlight(key, BUDGET_INTERACTIVE)
        leader.acquire()
        with mock.patch.object(single_flight, "FLIGHT_POLL_INTERVAL", 0.01):
            assert QuerySingleFlight(key, BUDGET_INTERACTIVE).wait(timeout_seconds=0.05) == FlightWait(
                outcome="timeout"
            )
        leader.release()

    def test_malformed_published_result_reads_as_released(self):
        flight = QuerySingleFlight(_cache_key(), BUDGET_INTERACTIVE)
        storage.query_cache_raw_client().set(flight.result_key, "not a timestamp")

        assert flight.wait(timeout_seconds=1) == FlightWait(outcome="released")

    def test_storage_errors_fail_open(self):
        flight = QuerySingleFlight(_cache_key(), BUDGET_INTERACTIVE)
        with mock.patch.object(single_flight.storage, "query_cache_raw_client", side_effect=RuntimeError("redis down")):
            assert flight.acquire() is True  # act alone rather than block the query
            assert flight.extend() is None  # ownership unknown, so the heartbeat keeps trying
            assert flight.wait(timeout_seconds=1) == FlightWait(outcome="released")  # run it yourself
            flight.succeed(datetime(2026, 1, 1, tzinfo=UTC))  # swallowed
