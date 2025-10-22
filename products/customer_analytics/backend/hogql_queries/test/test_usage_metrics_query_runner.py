from datetime import timedelta

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

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import UsageMetricsQuery

from posthog.models.group.util import create_group
from posthog.models.group_usage_metric import GroupUsageMetric
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.customer_analytics.backend.hogql_queries.usage_metrics_query_runner import UsageMetricsQueryRunner


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
