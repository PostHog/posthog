from datetime import datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, run_clickhouse_statement_in_parallel
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.utils.event_usage import (
    EVENT_USAGE_APP_SOURCE,
    MAX_EVENTS_LOGGED_PER_QUERY,
    MAX_PROPERTIES_LOGGED_PER_QUERY,
    PROPERTY_USAGE_APP_SOURCE,
    fetch_event_property_usage,
    fetch_most_used_event_names,
    log_event_usage_from_query_metadata,
)
from posthog.models.app_metrics2.sql import TRUNCATE_APP_METRICS2_TABLE_SQL
from posthog.test.fixtures import create_app_metric2


class TestLogEventUsageFromQueryMetadata(SimpleTestCase):
    def _producer(self, mock_get_producer: MagicMock) -> MagicMock:
        producer = MagicMock()
        mock_get_producer.return_value = producer
        return producer

    @patch("posthog.hogql_queries.utils.event_usage.get_producer")
    def test_logs_event_and_property_payloads(self, mock_get_producer):
        producer = self._producer(mock_get_producer)

        log_event_usage_from_query_metadata(
            {
                "events": ["$pageview"],
                "properties": [
                    {"type": "event", "name": "$browser"},
                    {"type": "person", "name": "email"},
                    {"type": "group", "group_type_index": 0, "name": "industry"},
                    {"type": "group", "group_type_index": 1, "name": "industry"},
                ],
            },
            team_id=42,
            user_id=7,
        )

        payloads = [call.kwargs["data"] for call in producer.produce.call_args_list]
        self.assertEqual(len(payloads), 5)

        property_payloads = [payload for payload in payloads if payload["app_source"] == "property_usage"]
        self.assertEqual(
            {payload["instance_id"] for payload in property_payloads},
            {
                "property:event:$browser",
                "property:person:email",
                "property:group:0:industry",
                "property:group:1:industry",
            },
        )
        for payload in property_payloads:
            self.assertEqual(payload["team_id"], 42)
            self.assertEqual(payload["metric_name"], "viewed")
            self.assertEqual(payload["app_source_id"], "7")

    @parameterized.expand(
        [
            (
                "events",
                {"events": [f"event_{i}" for i in range(60)], "properties": []},
                MAX_EVENTS_LOGGED_PER_QUERY,
            ),
            (
                "properties",
                {"events": [], "properties": [{"type": "event", "name": f"prop_{i}"} for i in range(60)]},
                MAX_PROPERTIES_LOGGED_PER_QUERY,
            ),
        ]
    )
    @patch("posthog.hogql_queries.utils.event_usage.get_producer")
    def test_caps_references_per_query(self, _name, query_metadata, cap, mock_get_producer):
        producer = self._producer(mock_get_producer)

        log_event_usage_from_query_metadata(query_metadata, team_id=42)

        self.assertEqual(producer.produce.call_count, cap)

    @patch("posthog.hogql_queries.utils.event_usage.get_producer")
    def test_skips_malformed_property_entries(self, mock_get_producer):
        producer = self._producer(mock_get_producer)

        log_event_usage_from_query_metadata(
            {
                "properties": [
                    "nope",
                    {"type": "event"},
                    {"name": "x"},
                    {"type": "group", "name": "no_index"},
                    {"type": "event", "name": "ok"},
                ]
            },
            team_id=42,
        )

        self.assertEqual(producer.produce.call_count, 1)
        self.assertEqual(producer.produce.call_args.kwargs["data"]["instance_id"], "property:event:ok")

    @patch("posthog.hogql_queries.utils.event_usage.get_producer")
    def test_metadata_without_properties_key_logs_nothing_extra(self, mock_get_producer):
        producer = self._producer(mock_get_producer)

        log_event_usage_from_query_metadata({"events": ["$pageview"]}, team_id=42)

        self.assertEqual(producer.produce.call_count, 1)


class TestUsageReaders(ClickhouseTestMixin, BaseTest):
    def test_readers_cover_only_the_team_and_the_last_30_days(self) -> None:
        run_clickhouse_statement_in_parallel([TRUNCATE_APP_METRICS2_TABLE_SQL])
        recent = datetime.now() - timedelta(hours=1)
        other_team_id = self.team.pk + 1000
        for team_id, app_source, instance_id, count, timestamp in [
            (self.team.pk, EVENT_USAGE_APP_SOURCE, "event:signed_up", 3, recent),
            (self.team.pk, EVENT_USAGE_APP_SOURCE, "event:signed_up", 2, recent - timedelta(days=2)),
            (self.team.pk, EVENT_USAGE_APP_SOURCE, "event:paid", 4, recent),
            (self.team.pk, EVENT_USAGE_APP_SOURCE, "event:retired", 50, recent - timedelta(days=40)),
            (other_team_id, EVENT_USAGE_APP_SOURCE, "event:elsewhere", 99, recent),
            (self.team.pk, PROPERTY_USAGE_APP_SOURCE, "property:event:amount", 7, recent),
            (self.team.pk, PROPERTY_USAGE_APP_SOURCE, "property:person:amount", 100, recent),
            (other_team_id, PROPERTY_USAGE_APP_SOURCE, "property:event:amount", 100, recent),
        ]:
            create_app_metric2(
                team_id=team_id,
                app_source=app_source,
                instance_id=instance_id,
                metric_name="viewed",
                count=count,
                timestamp=timestamp,
            )

        self.assertEqual(
            fetch_most_used_event_names(self.team, limit=10, workload=Workload.OFFLINE), ["signed_up", "paid"]
        )
        self.assertEqual(fetch_most_used_event_names(self.team, limit=1, workload=Workload.OFFLINE), ["signed_up"])
        self.assertEqual(
            fetch_event_property_usage(self.team, ["amount", "never_queried"], workload=Workload.OFFLINE),
            {"amount": 7},
        )
