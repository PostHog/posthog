from types import SimpleNamespace
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from clickhouse_driver.block import ColumnOrientedBlock
from parameterized import parameterized

from posthog.api_queries_budget import (
    API_QUERIES_BUDGET_ERRORS_COUNTER,
    API_QUERIES_CPU_BUDGET_LIMITED_COUNTER,
    API_QUERIES_CPU_BUDGET_UNMETERED_COUNTER,
    BUDGET_KEY_PREFIX,
    BUDGET_REDIS_TIMEOUT_SECONDS,
    LIMITED_EVENT,
    BudgetSpec,
    CpuBudgetStatus,
    QueryCost,
    budget_spec_for,
    claim_limited_event,
    debit,
    debit_org_cpu,
    get_request_query_cost,
    org_cpu_budget_status,
    record_request_query_cost,
    refill_and_read,
    reset_request_query_cost,
    seconds_until_positive,
)
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import MeteredQueryInfo, ProxyClient
from posthog.clickhouse.query_tagging import AccessMethod, Feature, Product, reset_query_tags, tag_queries
from posthog.redis import get_client

SPEC = BudgetSpec(bytes_per_hour=3600.0, capacity_bytes=7200.0)
CPU_BUDGET_SETTINGS = {"API_QUERIES_CPU_BUDGET_SECONDS_PER_HOUR": 1, "API_QUERIES_BUDGET_CAPACITY_HOURS": 24}
CPU_CAPACITY_US = 24_000_000


def _cpu_key(org_id: object) -> str:
    return f"{BUDGET_KEY_PREFIX}cpu/org/{org_id}"


def _cpu_tokens(org_id: object) -> float | None:
    tokens = get_client().hget(_cpu_key(org_id), "tokens")
    return None if tokens is None else float(tokens)


def _clear_cpu_budget(org_id: object) -> None:
    get_client().delete(_cpu_key(org_id), f"{BUDGET_KEY_PREFIX}limited-event/cpu/org/{org_id}")


@override_settings(
    API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR=70_000_000_000,
    API_QUERIES_BUDGET_PAID_MULTIPLIER=10,
    API_QUERIES_BUDGET_CAPACITY_HOURS=24,
    API_QUERIES_BUDGET_BYTES_PER_EVENT_PER_HOUR=1_000,
    API_QUERIES_BUDGET_MAX_BYTES_PER_HOUR=5_000e9,
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

    @parameterized.expand(
        [
            ("unknown_volume_keeps_floor", True, None, 700e9),
            ("small_volume_keeps_floor", True, 1_000, 700e9),
            ("volume_scales_above_floor", True, 1_000_000_000, 1_000e9),
            ("volume_is_capped", True, 100_000_000_000, 5_000e9),
            ("free_scales_from_its_own_floor", False, 100_000_000, 100e9),
        ]
    )
    def test_spec_scales_with_events_last_year(self, _name, has_active_subscription, events_last_year, per_hour):
        organization = SimpleNamespace(has_active_subscription=has_active_subscription)
        assert budget_spec_for(organization, events_last_year).bytes_per_hour == per_hour


@override_settings(API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR=70, API_QUERIES_BUDGET_CAPACITY_HOURS=24)
class TestTokenBucket(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team_id = str(uuid4())
        self.fresh_team_id = str(uuid4())

    def tearDown(self) -> None:
        get_client().delete(
            f"{BUDGET_KEY_PREFIX}team/{self.team_id}",
            f"{BUDGET_KEY_PREFIX}team/{self.fresh_team_id}",
        )
        super().tearDown()

    def test_budget_redis_calls_use_a_one_second_timeout(self):
        with patch("posthog.api_queries_budget.get_client") as get_client:
            refill_and_read(self.team_id, SPEC)

        get_client.assert_called_once_with(
            socket_timeout=BUDGET_REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=BUDGET_REDIS_TIMEOUT_SECONDS,
        )

    def test_fresh_bucket_starts_full(self):
        assert refill_and_read(self.team_id, SPEC, now=1000.0) == 7200.0

    def test_debit_then_refill_at_rate_capped_at_capacity(self):
        refill_and_read(self.team_id, SPEC, now=1000.0)
        assert debit(self.team_id, 5000) == 2200.0
        assert refill_and_read(self.team_id, SPEC, now=1001.0) == 2201.0
        assert refill_and_read(self.team_id, SPEC, now=99999.0) == 7200.0

    def test_negative_balance_reports_seconds_until_positive(self):
        refill_and_read(self.team_id, SPEC, now=1000.0)
        remaining = debit(self.team_id, 9000)
        assert remaining == -1800.0
        assert seconds_until_positive(remaining, SPEC) == 1800
        assert seconds_until_positive(5.0, SPEC) == 0
        assert seconds_until_positive(0.0, SPEC) == 1

    def test_balance_floors_at_minus_one_hour_of_refill(self):
        refill_and_read(self.team_id, SPEC, now=1000.0)
        assert debit(self.team_id, 50_000) == -3600.0
        assert seconds_until_positive(-3600.0, SPEC) == 3600
        assert refill_and_read(self.team_id, SPEC, now=1000.0 + 3600) == 0.0

    def test_debit_before_any_read_uses_the_free_capacity_and_floor(self):
        assert debit(self.fresh_team_id, 100) == 1580.0
        assert debit(self.fresh_team_id, 100) == 1480.0
        assert debit(self.fresh_team_id, 5000) == -70.0

    @override_settings(API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR=0)
    def test_disabled_budget_does_not_debit(self):
        assert debit(self.team_id, 1000) is None

    @override_settings(**CPU_BUDGET_SETTINGS)
    def test_org_cpu_bucket_counts_microseconds_and_floors_at_minus_one_hour(self):
        org_id = self.team_id
        assert org_cpu_budget_status(org_id, now=1000.0) == CpuBudgetStatus(
            remaining_cpu_us=CPU_CAPACITY_US, cpu_us_per_hour=1_000_000, retry_after_seconds=0
        )
        assert debit_org_cpu(org_id, 100 * CPU_CAPACITY_US) == -1_000_000
        status = org_cpu_budget_status(org_id, now=1000.0)
        assert status is not None and status.retry_after_seconds == 3600
        get_client().delete(_cpu_key(org_id))

    def test_disabled_cpu_budget_has_no_status_and_does_not_debit(self):
        assert org_cpu_budget_status(self.team_id) is None
        assert debit_org_cpu(self.team_id, 1000) is None
        assert _cpu_tokens(self.team_id) is None

    def test_redis_errors_fail_open_and_count(self):
        read_before = API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="read")._value.get()
        debit_before = API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="debit")._value.get()
        with patch("posthog.api_queries_budget.get_client", side_effect=Exception("redis down")):
            assert refill_and_read(self.team_id, SPEC) is None
            assert debit(self.team_id, 1) is None
        assert API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="read")._value.get() == read_before + 1
        assert API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="debit")._value.get() == debit_before + 1


class TestLimitedEventClaim(SimpleTestCase):
    def test_first_claim_per_team_wins_for_an_hour(self):
        team_a, team_b = f"team-{uuid4()}", f"team-{uuid4()}"
        assert claim_limited_event(team_a) is True
        assert claim_limited_event(team_a) is False
        assert claim_limited_event(team_b) is True
        assert get_client().ttl(f"{BUDGET_KEY_PREFIX}limited-event/{team_a}") > 0

    def test_redis_errors_skip_the_event_and_count(self):
        before = API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="limited_event")._value.get()
        with patch("posthog.api_queries_budget.get_client", side_effect=Exception("redis down")):
            assert claim_limited_event(f"team-{uuid4()}") is False
        assert API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="limited_event")._value.get() == before + 1


class TestRequestQueryCost(SimpleTestCase):
    def test_costs_accumulate_within_a_request_and_reset_between(self):
        reset_request_query_cost()
        assert get_request_query_cost() is None
        record_request_query_cost(QueryCost(bytes_read=100, remaining_bytes=50.0))
        record_request_query_cost(QueryCost(bytes_read=50, remaining_bytes=None))
        assert get_request_query_cost() == QueryCost(bytes_read=150, remaining_bytes=50.0)
        reset_request_query_cost()
        assert get_request_query_cost() is None


class TestBudgetedQueryMetering(ClickhouseTestMixin, BaseTest):
    # LIMIT applies to the aggregate's single output row, not to system.numbers itself,
    # so bound the scan inside a subquery or the read never terminates.
    BOUNDED_QUERY = "SELECT sum(number) FROM (SELECT number FROM system.numbers LIMIT 10000)"

    CPU_QUERY = "SELECT count() FROM numbers_mt(50000000) WHERE sipHash64(number) % 7 = 3"

    def setUp(self):
        super().setUp()
        reset_request_query_cost()
        _clear_cpu_budget(self.organization.pk)

    def tearDown(self):
        reset_query_tags()
        _clear_cpu_budget(self.organization.pk)
        super().tearDown()

    def _tag_api_key_query(self, **tags) -> str:
        client_query_id = str(uuid4())
        tag_queries(
            **{
                "access_method": AccessMethod.PERSONAL_API_KEY,
                "org_id": self.organization.pk,
                "team_id": self.team.pk,
                "product": Product.API,
                "client_query_id": client_query_id,
                **tags,
            }
        )
        return client_query_id

    def _query_log_cpu_us(self, client_query_id: str) -> int:
        sync_execute("SYSTEM FLUSH LOGS")
        rows = sync_execute(
            """
            SELECT sum(ProfileEvents['OSCPUVirtualTimeMicroseconds'])
            FROM system.query_log
            WHERE initial_query_id LIKE %(query_id)s AND type != 'QueryStart'
            """,
            {"query_id": f"{self.team.pk}_{client_query_id}_%"},
        )
        return int(rows[0][0])

    @override_settings(**CPU_BUDGET_SETTINGS)
    def test_api_key_query_debits_the_org_cpu_budget_by_the_cpu_query_log_reports(self):
        client_query_id = self._tag_api_key_query()
        sync_execute(self.CPU_QUERY)
        reset_query_tags()
        debited_us = CPU_CAPACITY_US - (_cpu_tokens(self.organization.pk) or CPU_CAPACITY_US)
        logged_us = self._query_log_cpu_us(client_query_id)
        assert logged_us > 100_000
        assert abs(debited_us - logged_us) <= 0.05 * logged_us

    @override_settings(**CPU_BUDGET_SETTINGS)
    def test_api_key_query_the_server_stops_still_debits_its_cpu(self):
        client_query_id = self._tag_api_key_query()
        with pytest.raises(Exception, match="max execution time"):
            sync_execute(
                "SELECT count() FROM numbers_mt(1000000000000) WHERE sipHash64(number) % 7 = 3",
                settings={"max_execution_time": 1},
            )
        reset_query_tags()
        debited_us = CPU_CAPACITY_US - (_cpu_tokens(self.organization.pk) or CPU_CAPACITY_US)
        assert debited_us >= 0.5 * self._query_log_cpu_us(client_query_id) > 0

    @parameterized.expand(
        [
            (
                "endpoint_execution",
                {"product": Product.ENDPOINTS, "feature": Feature.ENDPOINT_EXECUTION},
                CPU_BUDGET_SETTINGS,
            ),
            ("session_auth", {"access_method": None}, CPU_BUDGET_SETTINGS),
            ("project_secret_api_key", {"access_method": AccessMethod.PROJECT_SECRET_API_KEY}, CPU_BUDGET_SETTINGS),
            ("cpu_budget_disabled", {}, {"API_QUERIES_CPU_BUDGET_SECONDS_PER_HOUR": 0}),
        ]
    )
    def test_query_outside_the_cpu_budget_never_touches_it(self, _name, tags, budget_settings):
        with override_settings(**budget_settings):
            self._tag_api_key_query(**tags)
            sync_execute(self.BOUNDED_QUERY)
        assert not get_client().exists(_cpu_key(self.organization.pk))

    @parameterized.expand([("product_key", {"product": Product.ENDPOINTS}), ("scene", {"scene": "EndpointScene"})])
    @override_settings(**CPU_BUDGET_SETTINGS)
    def test_endpoints_tag_from_the_request_does_not_skip_the_cpu_budget(self, _name, tags):
        self._tag_api_key_query(**tags)
        sync_execute(self.BOUNDED_QUERY)
        assert get_client().exists(_cpu_key(self.organization.pk))

    @override_settings(**CPU_BUDGET_SETTINGS)
    def test_native_query_that_fails_before_any_profile_events_is_not_unmetered(self):
        before = API_QUERIES_CPU_BUDGET_UNMETERED_COUNTER._value.get()
        self._tag_api_key_query()
        with pytest.raises(Exception, match="Syntax error"):
            sync_execute("SELECT FROM WHERE")
        assert API_QUERIES_CPU_BUDGET_UNMETERED_COUNTER._value.get() == before

    @override_settings(**CPU_BUDGET_SETTINGS, CLOUD_DEPLOYMENT="EU")
    def test_exhausted_cpu_budget_is_counted_and_reported_once_but_never_refuses(self):
        debit_org_cpu(str(self.organization.pk), 100 * CPU_CAPACITY_US)
        before = API_QUERIES_CPU_BUDGET_LIMITED_COUNTER.labels(outcome="observed")._value.get()
        self._tag_api_key_query()
        with patch("posthog.api_queries_budget.ph_background_capture") as background_capture:
            capture = background_capture.return_value
            assert sync_execute(self.BOUNDED_QUERY) == [(49995000,)]
            assert sync_execute(self.BOUNDED_QUERY) == [(49995000,)]
        assert API_QUERIES_CPU_BUDGET_LIMITED_COUNTER.labels(outcome="observed")._value.get() == before + 2
        capture.assert_called_once()
        background_capture.assert_called_with(region="EU")
        assert capture.call_args.kwargs["event"] == LIMITED_EVENT
        assert capture.call_args.kwargs["distinct_id"] == str(self.organization.pk)
        properties = capture.call_args.kwargs["properties"]
        assert properties["budget"] == "cpu"
        assert properties["outcome"] == "observed"
        assert properties["product"] == "api"
        assert properties["remaining_cpu_seconds"] <= 0

    @override_settings(**CPU_BUDGET_SETTINGS)
    def test_analytics_failure_on_an_exhausted_cpu_budget_does_not_fail_the_query(self):
        debit_org_cpu(str(self.organization.pk), 100 * CPU_CAPACITY_US)
        errors = API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="cpu_check")
        before = errors._value.get()
        self._tag_api_key_query()
        with patch("posthog.api_queries_budget.ph_background_capture", side_effect=RuntimeError("analytics down")):
            assert sync_execute(self.BOUNDED_QUERY) == [(49995000,)]
        assert errors._value.get() == before + 1

    def test_budgeted_query_debits_the_team_budget(self):
        spec = budget_spec_for(self.organization)
        refill_and_read(str(self.team.pk), spec)
        tag_queries(api_queries_budgeted=True, team_id=self.team.pk)
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

    def test_chargeable_but_unbudgeted_query_is_not_metered(self):
        tag_queries(chargeable=1, team_id=self.team.pk)
        try:
            sync_execute(self.BOUNDED_QUERY)
        finally:
            reset_query_tags()
        assert get_request_query_cost() is None

    @parameterized.expand(
        [
            ("caller_supplied_endpoints_product_tag", {"product": Product.ENDPOINTS}),
            ("caller_supplied_data_catalog_product_tag", {"product": Product.DATA_CATALOG}),
        ]
    )
    def test_caller_supplied_tags_do_not_change_metering(self, _name, tags):
        tag_queries(api_queries_budgeted=True, team_id=self.team.pk, **tags)
        try:
            sync_execute(self.BOUNDED_QUERY)
        finally:
            reset_query_tags()
        cost = get_request_query_cost()
        assert cost is not None and cost.bytes_read > 0


class QueryDied(Exception):
    pass


@override_settings(**CPU_BUDGET_SETTINGS)
class TestFailedQueryMetering(BaseTest):
    def setUp(self):
        super().setUp()
        _clear_cpu_budget(self.organization.pk)

    def tearDown(self):
        _clear_cpu_budget(self.organization.pk)
        super().tearDown()

    def test_connection_failure_does_not_remeter_previous_query(self):
        reset_request_query_cost()
        fake_client = MagicMock()
        fake_client.last_query = SimpleNamespace(progress=SimpleNamespace(bytes=9999), cpu_us=9999)
        fake_client.execute.side_effect = QueryDied("network down before connecting")
        pool = MagicMock()
        pool.__enter__.return_value = fake_client
        tag_queries(
            api_queries_budgeted=True,
            team_id=self.team.pk,
            access_method=AccessMethod.PERSONAL_API_KEY,
            org_id=self.organization.pk,
        )
        try:
            with patch("posthog.clickhouse.client.execute.get_client_from_pool", return_value=pool):
                with pytest.raises(QueryDied):
                    sync_execute("SELECT 1")
        finally:
            reset_query_tags()
        assert get_request_query_cost() is None
        assert _cpu_tokens(self.organization.pk) == CPU_CAPACITY_US

    def test_http_client_query_counts_as_cpu_unmetered(self):
        http_client = MagicMock()
        http_client.query.return_value = SimpleNamespace(summary={"read_rows": "1"}, result_set=[(1,)])
        before = API_QUERIES_CPU_BUDGET_UNMETERED_COUNTER._value.get()
        tag_queries(team_id=self.team.pk, access_method=AccessMethod.PERSONAL_API_KEY, org_id=self.organization.pk)
        try:
            with patch("posthog.clickhouse.client.execute.get_client_from_pool", return_value=ProxyClient(http_client)):
                assert sync_execute("SELECT 1") == [(1,)]
        finally:
            reset_query_tags()
        assert API_QUERIES_CPU_BUDGET_UNMETERED_COUNTER._value.get() == before + 1
        assert _cpu_tokens(self.organization.pk) == CPU_CAPACITY_US


class TestMeteredQueryInfo(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero_rows", [("type", "String"), ("name", "String"), ("value", "Int64")], [], 0),
            (
                "renamed_column",
                [("kind", "String"), ("name", "String"), ("value", "Int64")],
                [["increment"], ["OSCPUVirtualTimeMicroseconds"], [5]],
                1,
            ),
        ]
    )
    def test_unreadable_profile_events_block_does_not_raise(self, _name, columns, data, expected_errors):
        errors = API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="cpu_packet")
        before = errors._value.get()
        query_info = MeteredQueryInfo()
        query_info.store_profile_events(ColumnOrientedBlock(columns, data))
        assert query_info.cpu_us == 0
        assert errors._value.get() == before + expected_errors


@override_settings(**CPU_BUDGET_SETTINGS)
class TestCpuBudgetCoversApiKeyRoutes(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        _clear_cpu_budget(self.organization.pk)

    def tearDown(self):
        _clear_cpu_budget(self.organization.pk)
        super().tearDown()

    @parameterized.expand([("events", "query:read"), ("persons", "person:read")])
    def test_api_key_list_route_observes_the_org_cpu_budget(self, route, scope):
        headers = {"Authorization": f"Bearer {self.create_personal_api_key_with_scopes([scope])}"}
        url = f"/api/projects/{self.team.id}/{route}/"

        debit_org_cpu(str(self.organization.pk), 100 * CPU_CAPACITY_US)
        before = API_QUERIES_CPU_BUDGET_LIMITED_COUNTER.labels(outcome="observed")._value.get()
        response = self.client.get(url, headers=headers)
        assert response.status_code == 200, response.content
        assert API_QUERIES_CPU_BUDGET_LIMITED_COUNTER.labels(outcome="observed")._value.get() > before
