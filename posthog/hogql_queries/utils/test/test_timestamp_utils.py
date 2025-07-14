import datetime
from django.test import override_settings

from posthog.hogql_queries.utils.timestamp_utils import get_earliest_timestamp_from_series
from posthog.schema import EventsNode
from posthog.test.base import APIBaseTest, _create_event


@override_settings(IN_UNIT_TESTING=True)
class TestTimestampUtils(APIBaseTest):
    def test_returns_earliest_timestamp_one_node(self):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2021-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2022-01-01T12:00:00Z",
        )

        series = [
            EventsNode(event="$pageview"),
        ]
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)

        self.assertEqual(earliest_timestamp, datetime.datetime(2021, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))

    def test_returns_earliest_timestamp_series_nodes(self):
        _create_event(
            team=self.team,
            event="$pageleave",
            distinct_id="person1",
            timestamp="2020-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person1",
            timestamp="2022-01-01T12:00:00Z",
        )

        series = [
            EventsNode(event="$pageview"),
            EventsNode(event="$pageleave"),
        ]
        earliest_timestamp = get_earliest_timestamp_from_series(self.team, series)

        self.assertEqual(earliest_timestamp, datetime.datetime(2020, 1, 1, 12, 0, 0, tzinfo=datetime.UTC))
