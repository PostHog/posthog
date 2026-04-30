from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import CachedUsageMetricsQueryResponse, UsageMetricsQuery

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.group.util import create_group
from posthog.models.group_usage_metric import GroupUsageMetric
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.customer_analytics.backend.hogql_queries.usage_metrics_query_runner import UsageMetricsQueryRunner
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv

DW_TEST_BUCKET = "test_storage_bucket-customer_analytics.usage_metrics"
DW_DATA_PATH = Path(__file__).parent / "data" / "usage_metrics_dw_data.csv"
DW_TABLE_COLUMNS = {
    "id": "String",
    "customer_id": "String",
    "created": "DateTime64(3, 'UTC')",
    "amount": "Float64",
}


@override_settings(IN_UNIT_TESTING=True)
class TestUsageMetricsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    person_distinct_id = "test-person-id"
    person_id = "cd6bb999-8652-4d98-a937-c49e89a5694d"
    another_person_distinct_id = "another-test-person-id"
    another_person_id = "c9636994-348f-48b5-88b8-fbdc13f95547"
    test_metric_id = "19bda517-7081-4004-8c1d-30d0b2b11bf5"
    another_test_metric_id = "1d2b5e4e-c338-4de9-af6c-9671d639ce1e"

    def setUp(self):
        super().setUp()
        self.person = _create_person(
            distinct_ids=[self.person_distinct_id],
            uuid=self.person_id,
            team=self.team,
            is_identified=True,
            properties={"email": "test@example.com", "name": "Test Person"},
        )
        self.another_person = _create_person(
            distinct_ids=[self.another_person_distinct_id],
            uuid=self.another_person_id,
            team=self.team,
            is_identified=True,
            properties={"email": "another_test@example.com", "name": "Another Test Person"},
        )
        flush_persons_and_events()

    def _calculate(self, group_key=None, group_type_index=None, person_id=None):
        return (
            UsageMetricsQueryRunner(
                team=self.team,
                query=UsageMetricsQuery(
                    kind="UsageMetricsQuery",
                    person_id=person_id,
                    group_key=group_key,
                    group_type_index=group_type_index,
                ),
            )
            .calculate()
            .model_dump()
        )

    def _create_group(self, group_key=None, group_type_index=0):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=group_type_index,
        )
        return create_group(
            team_id=self.team.pk,
            group_key=group_key,
            group_type_index=group_type_index,
            properties={"name": "Test Group"},
        )

    def test_init_with_person_id(self):
        query = UsageMetricsQuery(person_id="test-person-id")
        runner = UsageMetricsQueryRunner(team=self.team, query=query)
        assert runner.query.person_id == "test-person-id"
        assert runner._is_person_query is True
        assert runner._is_group_query is False

    @parameterized.expand(["test-group-key", "0"])
    def test_init_with_group_parameters(self, group_key: str):
        query = UsageMetricsQuery(group_key=group_key, group_type_index=0)
        runner = UsageMetricsQueryRunner(team=self.team, query=query)
        assert runner.query.group_key == group_key
        assert runner.query.group_type_index == 0
        assert runner._is_group_query is True
        assert runner._is_person_query is False

    @parameterized.expand(["", None])
    def test_init_with_neither_person_nor_group_raises_error(self, group_key: str | None):
        query = UsageMetricsQuery(group_key=group_key)
        with pytest.raises(ValueError, match="UsageMetricsQuery must have either group_key or person_id"):
            UsageMetricsQueryRunner(team=self.team, query=query)

    def test_init_with_both_person_and_group_raises_error(self):
        query = UsageMetricsQuery(person_id="test-person-id", group_key="test-group-key", group_type_index=0)
        with pytest.raises(ValueError, match="UsageMetricsQuery must have either group_key or person_id, not both"):
            UsageMetricsQueryRunner(team=self.team, query=query)

    def test_init_with_only_group_key_raises_error(self):
        query = UsageMetricsQuery(group_key="test-group-key")
        with pytest.raises(ValueError, match="UsageMetricsQuery must have either group_key or person_id"):
            UsageMetricsQueryRunner(team=self.team, query=query)

    def test_init_with_only_group_type_index_raises_error(self):
        query = UsageMetricsQuery(group_type_index=0)
        with pytest.raises(ValueError, match="UsageMetricsQuery must have either group_key or person_id"):
            UsageMetricsQueryRunner(team=self.team, query=query)

    @freeze_time("2025-10-09T12:11:00")
    @snapshot_clickhouse_queries
    def test_person_metric(self):
        metric = GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        another_metric = GroupUsageMetric.objects.create(
            id=self.another_test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Another test metric",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=30,
            display=GroupUsageMetric.Display.SPARKLINE,
            filters={"events": [{"id": "another_metric_event", "type": "events", "order": 0}]},
        )
        for _ in range(3):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
            )
        for _ in range(5):
            _create_event(
                event="another_metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
            )
            # Create events for another person to assert filter by person_id works
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.another_person.uuid),
                distinct_id=self.another_person_distinct_id,
            )
            _create_event(
                event="another_metric_event",
                team=self.team,
                person_id=str(self.another_person.uuid),
                distinct_id=self.another_person_distinct_id,
            )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["display"], metric.display)
        self.assertEqual(results[0]["format"], metric.format)
        self.assertEqual(results[0]["id"], str(metric.id))
        self.assertEqual(results[0]["interval"], metric.interval)
        self.assertEqual(results[0]["name"], metric.name)
        self.assertEqual(results[0]["value"], 3.0)

        self.assertEqual(results[1]["id"], str(another_metric.id))
        self.assertEqual(results[1]["value"], 5.0)

    @freeze_time("2025-10-09T12:11:00")
    @snapshot_clickhouse_queries
    def test_complex_event_filter(self):
        metric = GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={
                "events": [{"id": "metric_event", "type": "events", "order": 0}],
                "properties": [{"key": "$browser", "type": "event", "value": ["Chrome"], "operator": "exact"}],
            },
        )
        for _ in range(3):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
                properties={"$browser": "Chrome"},
            )
        for _ in range(5):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
                properties={"$browser": "Firefox"},
            )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(metric.id))
        self.assertEqual(results[0]["value"], 3.0)

    @freeze_time("2025-10-09T12:11:00")
    @snapshot_clickhouse_queries
    def test_metric_interval(self):
        metric = GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={
                "events": [{"id": "metric_event", "type": "events", "order": 0}],
            },
        )

        with freeze_time(timezone.now() - timedelta(days=8)):
            # These should not count in `value`, but should count in `previous`
            for _ in range(3):
                _create_event(
                    event="metric_event",
                    team=self.team,
                    person_id=str(self.person.uuid),
                    distinct_id=self.person_distinct_id,
                )

        with freeze_time(timezone.now() - timedelta(days=7)):
            # These should count in `value` only, as date_from check is gte and `previous` check is lt
            for _ in range(2):
                _create_event(
                    event="metric_event",
                    team=self.team,
                    person_id=str(self.person.uuid),
                    distinct_id=self.person_distinct_id,
                )

        with freeze_time(timezone.now()):
            # These should count, as date_to check is lte
            for _ in range(2):
                _create_event(
                    event="metric_event",
                    team=self.team,
                    person_id=str(self.person.uuid),
                    distinct_id=self.person_distinct_id,
                )

        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(metric.id))
        self.assertEqual(results[0]["value"], 4.0)
        self.assertEqual(results[0]["previous"], 3.0)
        self.assertEqual(results[0]["change_from_previous_pct"], 33.33333333333333)

    @freeze_time("2025-10-09T12:11:00")
    @snapshot_clickhouse_queries
    def test_handles_failed_metric_gracefully(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={},
        )

        for _ in range(2):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
            )

        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 0)

    @freeze_time("2025-10-09T12:11:00")
    @snapshot_clickhouse_queries
    def test_no_metrics(self):
        for _ in range(3):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
            )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 0)

    @freeze_time("2025-10-09T12:11:00")
    @snapshot_clickhouse_queries
    def test_group_metric(self):
        group_key = "test_group"
        self._create_group(group_key=group_key, group_type_index=0)
        metric = GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        another_metric = GroupUsageMetric.objects.create(
            id=self.another_test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Another test metric",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=30,
            display=GroupUsageMetric.Display.SPARKLINE,
            filters={"events": [{"id": "another_metric_event", "type": "events", "order": 0}]},
        )
        for _ in range(3):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
                properties={"$group_0": group_key},
            )
        for _ in range(5):
            _create_event(
                event="another_metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
                properties={"$group_0": group_key},
            )
            # Events with no group should not be counted
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.another_person.uuid),
                distinct_id=self.another_person_distinct_id,
            )
            _create_event(
                event="another_metric_event",
                team=self.team,
                person_id=str(self.another_person.uuid),
                distinct_id=self.another_person_distinct_id,
            )
        flush_persons_and_events()

        query_result = self._calculate(group_type_index=0, group_key=group_key)

        results = query_result["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], str(metric.id))
        self.assertEqual(results[0]["value"], 3.0)
        self.assertEqual(results[1]["id"], str(another_metric.id))
        self.assertEqual(results[1]["value"], 5.0)

    @freeze_time("2025-10-09T12:11:00")
    @snapshot_clickhouse_queries
    def test_sum_math_aggregation(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Revenue",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "purchase", "type": "events", "order": 0}]},
            math=GroupUsageMetric.Math.SUM,
            math_property="amount",
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
            properties={"amount": 100},
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
            properties={"amount": 250.5},
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.another_person.uuid),
            distinct_id=self.another_person_distinct_id,
            properties={"amount": 999},
        )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Revenue")
        self.assertEqual(results[0]["value"], 350.5)

    @freeze_time("2025-10-09T12:11:00")
    def test_sum_math_with_missing_property_returns_zero(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Revenue",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "purchase", "type": "events", "order": 0}]},
            math=GroupUsageMetric.Math.SUM,
            math_property="amount",
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
            properties={},
        )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["value"], 0.0)

    @freeze_time("2025-10-09T12:11:00")
    def test_sum_math_with_null_math_property_returns_zero(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Revenue",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "purchase", "type": "events", "order": 0}]},
            math=GroupUsageMetric.Math.SUM,
            math_property=None,
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
            properties={"amount": 100},
        )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 0)

    @freeze_time("2025-10-09T12:11:00")
    def test_sum_math_previous_period_comparison(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Revenue",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "purchase", "type": "events", "order": 0}]},
            math=GroupUsageMetric.Math.SUM,
            math_property="amount",
        )

        with freeze_time(timezone.now() - timedelta(days=8)):
            _create_event(
                event="purchase",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
                properties={"amount": 200},
            )

        with freeze_time(timezone.now()):
            _create_event(
                event="purchase",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
                properties={"amount": 300},
            )

        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["value"], 300.0)
        self.assertEqual(results[0]["previous"], 200.0)
        self.assertEqual(results[0]["change_from_previous_pct"], 50.0)

    @freeze_time("2025-10-09T12:11:00")
    def test_count_and_sum_metrics_together(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Purchases",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "purchase", "type": "events", "order": 0}]},
        )
        GroupUsageMetric.objects.create(
            id=self.another_test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Revenue",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "purchase", "type": "events", "order": 0}]},
            math=GroupUsageMetric.Math.SUM,
            math_property="amount",
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
            properties={"amount": 100},
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
            properties={"amount": 200},
        )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 2)
        results_by_name = {r["name"]: r for r in results}
        self.assertEqual(results_by_name["Revenue"]["value"], 300.0)
        self.assertEqual(results_by_name["Purchases"]["value"], 2.0)

    @freeze_time("2025-10-09T12:11:00")
    def test_cache_invalidates_when_metric_created(self):
        _create_event(
            event="metric_event",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
        )
        flush_persons_and_events()
        runner = UsageMetricsQueryRunner(
            team=self.team,
            query=UsageMetricsQuery(kind="UsageMetricsQuery", person_id=str(self.person.uuid)),
        )

        response1 = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

        assert isinstance(response1, CachedUsageMetricsQueryResponse)
        self.assertFalse(response1.is_cached)
        self.assertEqual(len(response1.results), 0)

        GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        runner2 = UsageMetricsQueryRunner(
            team=self.team,
            query=UsageMetricsQuery(kind="UsageMetricsQuery", person_id=str(self.person.uuid)),
        )

        response2 = runner2.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

        assert isinstance(response2, CachedUsageMetricsQueryResponse)
        self.assertFalse(response2.is_cached)
        self.assertEqual(len(response2.results), 1)
        self.assertEqual(response2.results[0].name, "Test metric")
        self.assertEqual(response2.results[0].value, 1.0)

    @freeze_time("2025-10-09T12:11:00")
    def test_cache_invalidates_when_metric_deleted(self):
        _create_event(
            event="metric_event",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
        )
        flush_persons_and_events()
        metric = GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        runner = UsageMetricsQueryRunner(
            team=self.team,
            query=UsageMetricsQuery(kind="UsageMetricsQuery", person_id=str(self.person.uuid)),
        )

        response1 = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

        assert isinstance(response1, CachedUsageMetricsQueryResponse)
        self.assertFalse(response1.is_cached)
        self.assertEqual(len(response1.results), 1)
        self.assertEqual(response1.results[0].name, "Test metric")

        metric.delete()
        runner2 = UsageMetricsQueryRunner(
            team=self.team,
            query=UsageMetricsQuery(kind="UsageMetricsQuery", person_id=str(self.person.uuid)),
        )

        response2 = runner2.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

        assert isinstance(response2, CachedUsageMetricsQueryResponse)
        self.assertFalse(response2.is_cached)
        self.assertEqual(len(response2.results), 0)

    @freeze_time("2025-10-09T12:11:00")
    def test_usage_metrics_fetched_once_per_runner(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        runner = UsageMetricsQueryRunner(
            team=self.team,
            query=UsageMetricsQuery(kind="UsageMetricsQuery", person_id=str(self.person.uuid)),
        )

        with patch.object(GroupUsageMetric.objects, "filter", wraps=GroupUsageMetric.objects.filter) as filter_spy:
            runner.get_cache_payload()
            runner.calculate()
            runner.to_query()

        self.assertEqual(filter_spy.call_count, 1)

    @freeze_time("2025-10-09T12:11:00")
    def test_datetime_now_shared_between_query_build_and_post_process(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Test metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        _create_event(
            event="metric_event",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
        )
        flush_persons_and_events()

        fake_now = datetime(2025, 10, 9, 12, 11, 0, tzinfo=ZoneInfo("UTC"))
        call_log: list[datetime] = []

        class TimeDriftingDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                # Each call advances by 12 hours to simulate worst-case drift across the day boundary
                value = fake_now + timedelta(hours=12 * len(call_log))
                call_log.append(value)
                return value

        with patch(
            "products.customer_analytics.backend.hogql_queries.usage_metrics_query_runner.datetime",
            TimeDriftingDatetime,
        ):
            runner = UsageMetricsQueryRunner(
                team=self.team,
                query=UsageMetricsQuery(kind="UsageMetricsQuery", person_id=str(self.person.uuid)),
            )
            query_result = runner.calculate().model_dump()

        self.assertEqual(len(call_log), 1)
        results = query_result["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["value"], 1.0)

    @freeze_time("2025-10-09T12:11:00")
    def test_sparkline_returns_timeseries(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Events",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.SPARKLINE,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        with freeze_time(timezone.now() - timedelta(days=2)):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
            )
        with freeze_time(timezone.now()):
            for _ in range(3):
                _create_event(
                    event="metric_event",
                    team=self.team,
                    person_id=str(self.person.uuid),
                    distinct_id=self.person_distinct_id,
                )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["display"], "sparkline")
        self.assertEqual(result["value"], 4.0)
        self.assertIsNotNone(result["timeseries"])
        self.assertIsNotNone(result["timeseries_labels"])
        self.assertEqual(len(result["timeseries"]), len(result["timeseries_labels"]))
        self.assertEqual(sum(result["timeseries"]), 4.0)

    @freeze_time("2025-10-09T12:11:00")
    def test_number_metric_no_timeseries(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Events",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        _create_event(
            event="metric_event",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
        )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["timeseries"])
        self.assertIsNone(results[0]["timeseries_labels"])

    @freeze_time("2025-10-09T12:11:00")
    def test_sparkline_gap_filling(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Events",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.SPARKLINE,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        with freeze_time(timezone.now() - timedelta(days=5)):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
            )
        with freeze_time(timezone.now() - timedelta(days=1)):
            _create_event(
                event="metric_event",
                team=self.team,
                person_id=str(self.person.uuid),
                distinct_id=self.person_distinct_id,
            )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        timeseries = results[0]["timeseries"]
        self.assertIsNotNone(timeseries)
        self.assertEqual(sum(timeseries), 2.0)
        zero_count = sum(1 for v in timeseries if v == 0.0)
        self.assertEqual(zero_count, len(timeseries) - 2)

    @freeze_time("2025-10-09T12:11:00")
    def test_sparkline_sum_aggregation(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Revenue",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=7,
            display=GroupUsageMetric.Display.SPARKLINE,
            filters={"events": [{"id": "purchase", "type": "events", "order": 0}]},
            math=GroupUsageMetric.Math.SUM,
            math_property="amount",
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
            properties={"amount": 100.5},
        )
        _create_event(
            event="purchase",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
            properties={"amount": 250},
        )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["display"], "sparkline")
        self.assertIsNotNone(result["timeseries"])
        self.assertEqual(sum(result["timeseries"]), 350.5)

    @freeze_time("2025-10-09T12:11:00")
    def test_mixed_display_types(self):
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Number metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        GroupUsageMetric.objects.create(
            id=self.another_test_metric_id,
            team=self.team,
            group_type_index=0,
            name="Sparkline metric",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.SPARKLINE,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        _create_event(
            event="metric_event",
            team=self.team,
            person_id=str(self.person.uuid),
            distinct_id=self.person_distinct_id,
        )
        flush_persons_and_events()

        query_result = self._calculate(person_id=str(self.person.uuid))

        results = query_result["results"]
        self.assertEqual(len(results), 2)
        results_by_name = {r["name"]: r for r in results}

        number_result = results_by_name["Number metric"]
        self.assertEqual(number_result["value"], 1.0)
        self.assertIsNone(number_result["timeseries"])

        sparkline_result = results_by_name["Sparkline metric"]
        self.assertEqual(sparkline_result["value"], 1.0)
        self.assertIsNotNone(sparkline_result["timeseries"])


@override_settings(IN_UNIT_TESTING=True)
class TestUsageMetricsQueryRunnerDataWarehouse(ClickhouseTestMixin, APIBaseTest):
    group_key = "acme"
    test_metric_id = "19bda517-7081-4004-8c1d-30d0b2b11bf5"

    def setUp(self):
        super().setUp()
        self._cleanup_dw = None

    def tearDown(self):
        if self._cleanup_dw is not None:
            self._cleanup_dw()
        super().tearDown()

    def _setup_dw_table(self) -> str:
        table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
            csv_path=DW_DATA_PATH,
            table_name="usage_metrics",
            table_columns=DW_TABLE_COLUMNS,
            test_bucket=DW_TEST_BUCKET,
            team=self.team,
        )
        self._cleanup_dw = cleanup
        return table.name

    def _setup_group(self, group_key: str | None = None) -> None:
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        create_group(
            team_id=self.team.pk,
            group_key=group_key or self.group_key,
            group_type_index=0,
            properties={"name": "Test Group"},
        )

    def _calculate(self, group_key: str | None = None, person_id: str | None = None):
        return (
            UsageMetricsQueryRunner(
                team=self.team,
                query=UsageMetricsQuery(
                    kind="UsageMetricsQuery",
                    person_id=person_id,
                    group_key=group_key,
                    group_type_index=0 if group_key else None,
                ),
            )
            .calculate()
            .model_dump()
        )

    def test_data_warehouse_count_metric(self):
        self._setup_group()
        table_name = self._setup_dw_table()
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="DW signups",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={
                "source": "data_warehouse",
                "table_name": table_name,
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
            math=GroupUsageMetric.Math.COUNT,
        )

        with freeze_time("2025-10-09T12:11:00"):
            results = self._calculate(group_key=self.group_key)["results"]

        assert len(results) == 1
        assert results[0]["name"] == "DW signups"
        assert results[0]["value"] == 3.0
        assert results[0]["previous"] == 1.0

    def test_data_warehouse_sum_metric(self):
        self._setup_group()
        table_name = self._setup_dw_table()
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="DW revenue",
            format=GroupUsageMetric.Format.CURRENCY,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={
                "source": "data_warehouse",
                "table_name": table_name,
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
            math=GroupUsageMetric.Math.SUM,
            math_property="amount",
        )

        with freeze_time("2025-10-09T12:11:00"):
            results = self._calculate(group_key=self.group_key)["results"]

        assert len(results) == 1
        assert results[0]["value"] == 425.5
        assert results[0]["previous"] == 500.0

    def test_data_warehouse_group_key_mismatch_returns_zero(self):
        self._setup_group(group_key="nobody")
        table_name = self._setup_dw_table()
        GroupUsageMetric.objects.create(
            id=self.test_metric_id,
            team=self.team,
            group_type_index=0,
            name="DW signups",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={
                "source": "data_warehouse",
                "table_name": table_name,
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        )

        with freeze_time("2025-10-09T12:11:00"):
            results = self._calculate(group_key="nobody")["results"]

        assert len(results) == 1
        assert results[0]["value"] == 0.0
        assert results[0]["previous"] == 0.0

    def test_mixed_events_and_data_warehouse_metrics(self):
        person = _create_person(
            distinct_ids=["dw-mixed-test-person"], team=self.team, properties={"email": "x@example.com"}
        )
        self._setup_group()
        table_name = self._setup_dw_table()
        GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="Events count",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={"events": [{"id": "metric_event", "type": "events", "order": 0}]},
        )
        GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="DW count",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={
                "source": "data_warehouse",
                "table_name": table_name,
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        )
        with freeze_time("2025-10-09T12:11:00"):
            for _ in range(2):
                _create_event(
                    event="metric_event",
                    team=self.team,
                    person_id=str(person.uuid),
                    distinct_id="dw-mixed-test-person",
                    properties={"$group_0": self.group_key},
                )
            flush_persons_and_events()

            results = self._calculate(group_key=self.group_key)["results"]

        by_name = {r["name"]: r for r in results}
        assert by_name["Events count"]["value"] == 2.0
        assert by_name["DW count"]["value"] == 3.0

    def test_data_warehouse_metric_skipped_on_person_query(self):
        person = _create_person(distinct_ids=["dw-person"], team=self.team, properties={})
        flush_persons_and_events()
        table_name = self._setup_dw_table()
        GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="DW signups",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={
                "source": "data_warehouse",
                "table_name": table_name,
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        )

        with freeze_time("2025-10-09T12:11:00"):
            results = self._calculate(person_id=str(person.uuid))["results"]

        assert results == []

    def test_cache_invalidates_when_data_warehouse_field_edited(self):
        self._setup_group()
        table_name = self._setup_dw_table()
        metric = GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="DW signups",
            format=GroupUsageMetric.Format.NUMERIC,
            interval=7,
            display=GroupUsageMetric.Display.NUMBER,
            filters={
                "source": "data_warehouse",
                "table_name": table_name,
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        )
        runner1 = UsageMetricsQueryRunner(
            team=self.team,
            query=UsageMetricsQuery(kind="UsageMetricsQuery", group_key=self.group_key, group_type_index=0),
        )
        key1 = runner1.get_cache_payload()["usage_metric_fingerprints"]

        metric.filters["timestamp_field"] = "toDateTime(created)"
        metric.save(update_fields=["filters"])

        runner2 = UsageMetricsQueryRunner(
            team=self.team,
            query=UsageMetricsQuery(kind="UsageMetricsQuery", group_key=self.group_key, group_type_index=0),
        )
        key2 = runner2.get_cache_payload()["usage_metric_fingerprints"]

        assert key1 != key2
