from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.api_queries_budget import (
    API_QUERIES_BUDGET_ERRORS_COUNTER,
    BudgetSpec,
    QueryCost,
    budget_spec_for,
    debit,
    get_request_query_cost,
    record_request_query_cost,
    refill_and_read,
    reset_request_query_cost,
    seconds_until_positive,
)
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import reset_query_tags, tag_queries

SPEC = BudgetSpec(bytes_per_hour=3600.0, capacity_bytes=7200.0)


@override_settings(
    API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR=70_000_000_000,
    API_QUERIES_BUDGET_PAID_MULTIPLIER=10,
    API_QUERIES_BUDGET_CAPACITY_HOURS=24,
)
class TestBudgetSpecFor(SimpleTestCase):
    @parameterized.expand(
        [
            ("free", False, 70e9, 1680e9),
            ("paying", True, 700e9, 16800e9),
            ("unknown_fails_open_to_paying", None, 700e9, 16800e9),
        ]
    )
    def test_spec_by_subscription(self, _name, has_active_subscription, per_hour, capacity):
        organization = SimpleNamespace(has_active_subscription=has_active_subscription)
        assert budget_spec_for(organization) == BudgetSpec(bytes_per_hour=per_hour, capacity_bytes=capacity)


@override_settings(API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR=70, API_QUERIES_BUDGET_CAPACITY_HOURS=24)
class TestTokenBucket(BaseTest):
    def test_fresh_bucket_starts_full(self):
        assert refill_and_read("team-a", SPEC, now=1000.0) == 7200.0

    def test_debit_then_refill_at_rate_capped_at_capacity(self):
        refill_and_read("team-a", SPEC, now=1000.0)
        assert debit("team-a", 5000) == 2200.0
        assert refill_and_read("team-a", SPEC, now=1001.0) == 2201.0
        assert refill_and_read("team-a", SPEC, now=99999.0) == 7200.0

    def test_negative_balance_reports_seconds_until_positive(self):
        refill_and_read("team-a", SPEC, now=1000.0)
        remaining = debit("team-a", 9000)
        assert remaining == -1800.0
        assert seconds_until_positive(remaining, SPEC) == 1800
        assert seconds_until_positive(5.0, SPEC) == 0
        assert seconds_until_positive(0.0, SPEC) == 1

    def test_balance_floors_at_minus_one_hour_of_refill(self):
        refill_and_read("team-a", SPEC, now=1000.0)
        assert debit("team-a", 50_000) == -3600.0
        assert seconds_until_positive(-3600.0, SPEC) == 3600
        assert refill_and_read("team-a", SPEC, now=1000.0 + 3600) == 0.0

    def test_debit_before_any_read_uses_the_free_capacity_and_floor(self):
        assert debit("team-new", 100) == 1580.0
        assert debit("team-new", 100) == 1480.0
        assert debit("team-new", 5000) == -70.0

    @override_settings(API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR=0)
    def test_disabled_budget_does_not_debit(self):
        assert debit("team-a", 1000) is None

    def test_redis_errors_fail_open_and_count(self):
        read_before = API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="read")._value.get()
        debit_before = API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="debit")._value.get()
        with patch("posthog.api_queries_budget.get_client", side_effect=Exception("redis down")):
            assert refill_and_read("team-a", SPEC) is None
            assert debit("team-a", 1) is None
        assert API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="read")._value.get() == read_before + 1
        assert API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="debit")._value.get() == debit_before + 1


class TestRequestQueryCost(SimpleTestCase):
    def test_costs_accumulate_within_a_request_and_reset_between(self):
        reset_request_query_cost()
        assert get_request_query_cost() is None
        record_request_query_cost(QueryCost(bytes_read=100, remaining_bytes=50.0))
        record_request_query_cost(QueryCost(bytes_read=50, remaining_bytes=None))
        assert get_request_query_cost() == QueryCost(bytes_read=150, remaining_bytes=50.0)
        reset_request_query_cost()
        assert get_request_query_cost() is None


class TestChargeableQueryMetering(ClickhouseTestMixin, BaseTest):
    # LIMIT applies to the aggregate's single output row, not to system.numbers itself,
    # so bound the scan inside a subquery or the read never terminates.
    BOUNDED_QUERY = "SELECT sum(number) FROM (SELECT number FROM system.numbers LIMIT 10000)"

    def setUp(self):
        super().setUp()
        reset_request_query_cost()

    def test_chargeable_query_debits_the_team_budget(self):
        spec = budget_spec_for(self.organization)
        refill_and_read(str(self.team.pk), spec)
        tag_queries(chargeable=1, team_id=self.team.pk)
        try:
            sync_execute(self.BOUNDED_QUERY)
        finally:
            reset_query_tags()
        cost = get_request_query_cost()
        assert cost is not None and cost.bytes_read > 0
        assert cost.remaining_bytes is not None and cost.remaining_bytes < spec.capacity_bytes

    def test_untagged_query_is_not_metered(self):
        sync_execute(self.BOUNDED_QUERY)
        assert get_request_query_cost() is None


class QueryDied(Exception):
    pass


class TestFailedQueryMetering(BaseTest):
    def test_connection_failure_does_not_remeter_previous_query(self):
        reset_request_query_cost()
        fake_client = MagicMock()
        fake_client.last_query = SimpleNamespace(progress=SimpleNamespace(bytes=9999))
        fake_client.execute.side_effect = QueryDied("network down before connecting")
        pool = MagicMock()
        pool.__enter__.return_value = fake_client
        tag_queries(chargeable=1, team_id=self.team.pk)
        try:
            with patch("posthog.clickhouse.client.execute.get_client_from_pool", return_value=pool):
                with pytest.raises(QueryDied):
                    sync_execute("SELECT 1")
        finally:
            reset_query_tags()
        assert get_request_query_cost() is None
