from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.api_queries_quota import get_api_queries_bytes, increment_api_queries_bytes, next_counter_reset


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

    def test_next_counter_reset_rolls_month_and_year(self):
        assert next_counter_reset(datetime(2026, 8, 12, tzinfo=UTC)) == datetime(2026, 9, 1, tzinfo=UTC)
        assert next_counter_reset(datetime(2026, 12, 31, tzinfo=UTC)) == datetime(2027, 1, 1, tzinfo=UTC)
