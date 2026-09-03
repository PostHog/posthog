from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from posthog.api_queries_quota import (
    API_QUERIES_QUOTA_ERRORS_COUNTER,
    get_api_queries_bytes,
    increment_api_queries_bytes,
    next_counter_reset,
)
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import reset_query_tags, tag_queries


class TestApiQueriesQuotaCounter(BaseTest):
    def test_increment_then_read_round_trips(self):
        increment_api_queries_bytes("org-a", 1000)
        increment_api_queries_bytes("org-a", 500)
        assert get_api_queries_bytes("org-a") == 1500

    def test_missing_key_reads_zero(self):
        assert get_api_queries_bytes("org-never-seen") == 0

    def test_zero_bytes_is_noop(self):
        increment_api_queries_bytes("org-a", 0)
        assert get_api_queries_bytes("org-a") == 0

    def test_redis_errors_fail_open(self):
        with patch("posthog.api_queries_quota.get_client", side_effect=Exception("redis down")):
            increment_api_queries_bytes("org-a", 1000)  # must not raise
            assert get_api_queries_bytes("org-a") == 0

    def test_increment_error_increments_error_counter(self):
        before = API_QUERIES_QUOTA_ERRORS_COUNTER.labels(op="increment")._value.get()
        with patch("posthog.api_queries_quota.get_client", side_effect=Exception("redis down")):
            increment_api_queries_bytes("org-a", 1000)
        after = API_QUERIES_QUOTA_ERRORS_COUNTER.labels(op="increment")._value.get()
        assert after == before + 1

    def test_read_error_increments_error_counter(self):
        before = API_QUERIES_QUOTA_ERRORS_COUNTER.labels(op="read")._value.get()
        with patch("posthog.api_queries_quota.get_client", side_effect=Exception("redis down")):
            get_api_queries_bytes("org-a")
        after = API_QUERIES_QUOTA_ERRORS_COUNTER.labels(op="read")._value.get()
        assert after == before + 1

    def test_next_counter_reset_rolls_month_and_year(self):
        assert next_counter_reset(datetime(2026, 8, 12, tzinfo=UTC)) == datetime(2026, 9, 1, tzinfo=UTC)
        assert next_counter_reset(datetime(2026, 12, 31, tzinfo=UTC)) == datetime(2027, 1, 1, tzinfo=UTC)


class TestChargeableByteMetering(ClickhouseTestMixin, BaseTest):
    # LIMIT applies to the aggregate's single output row, not to system.numbers itself,
    # so bound the scan inside a subquery or the read never terminates.
    BOUNDED_QUERY = "SELECT sum(number) FROM (SELECT number FROM system.numbers LIMIT 10000)"

    def test_chargeable_tagged_query_increments_counter(self):
        tag_queries(chargeable=1, org_id=self.organization.id)
        try:
            sync_execute(self.BOUNDED_QUERY)
        finally:
            reset_query_tags()
        assert get_api_queries_bytes(str(self.organization.id)) > 0

    def test_untagged_query_does_not_count(self):
        sync_execute(self.BOUNDED_QUERY)
        assert get_api_queries_bytes(str(self.organization.id)) == 0


class QueryDied(Exception):
    pass


class TestFailedQueryMetering(BaseTest):
    def _sync_execute_with_fake_client(self, fake_client):
        pool = MagicMock()
        pool.__enter__.return_value = fake_client
        tag_queries(chargeable=1, org_id=self.organization.id)
        try:
            with patch("posthog.clickhouse.client.execute.get_client_from_pool", return_value=pool):
                with pytest.raises(QueryDied):
                    sync_execute("SELECT 1")
        finally:
            reset_query_tags()

    def test_killed_query_meters_progress_reported_before_death(self):
        fake_client = MagicMock()

        def die_mid_scan(*args, **kwargs):
            fake_client.last_query = SimpleNamespace(progress=SimpleNamespace(bytes=4444))
            raise QueryDied("timeout")

        fake_client.execute.side_effect = die_mid_scan
        self._sync_execute_with_fake_client(fake_client)
        assert get_api_queries_bytes(str(self.organization.id)) == 4444

    def test_connection_failure_does_not_remeter_previous_query(self):
        fake_client = MagicMock()
        fake_client.last_query = SimpleNamespace(progress=SimpleNamespace(bytes=9999))
        fake_client.execute.side_effect = QueryDied("network down before connecting")
        self._sync_execute_with_fake_client(fake_client)
        assert get_api_queries_bytes(str(self.organization.id)) == 0
