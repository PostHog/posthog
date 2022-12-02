import json

from posthog.client import sync_execute
from posthog.models.live_events.sql import INSERT_INTO_LIVE_EVENTS_SQL, SELECT_LIVE_EVENTS_BY_TEAM_AND_CONDITIONS_SQL
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.test.base import BaseTest, _create_event

events = [
    {
        "uuid": "587c7f8a-2ab7-4741-a893-22d0e57e420c",
        "event": "event1",
        "properties": {"foo": "bar"},
        "timestamp": "2022-12-02 00:01:00",
        "team_id": 1,
        "distinct_id": "some-distinct-id",
    },
    {
        "uuid": "4c65cedb-97a6-4d29-a090-48b09c433e7b",
        "event": "event2",
        "properties": {"foo": "bar"},
        "timestamp": "2022-12-02 00:01:10",
        "team_id": 1,
        "distinct_id": "some-distinct-id",
    },
    {
        "uuid": "0fe40d78-0e6b-4ab5-805e-b3fde8c51f42",
        "event": "event3",
        "properties": {"foo": "bar"},
        "timestamp": "2022-12-02 00:01:20",
        "team_id": 1,
        "distinct_id": "some-distinct-id",
    },
]


class TestLiveEvents(BaseTest):
    def setUp(self):
        sync_execute("TRUNCATE TABLE sharded_events")
        sync_execute("TRUNCATE TABLE sharded_live_events")

    def test_all_events_on_both_tables(self):
        # create all 3 events on both tables
        for event in events:
            _create_event(
                event_uuid=event["uuid"],
                event=event["event"],
                properties=event["properties"],
                timestamp=event["timestamp"],
                team_id=event["team_id"],
                distinct_id=event["distinct_id"],
            )
            sync_execute(
                INSERT_INTO_LIVE_EVENTS_SQL,
                {
                    "uuid": event["uuid"],
                    "event": event["event"],
                    "properties": json.dumps(event["properties"]),
                    "timestamp": event["timestamp"],
                    "team_id": event["team_id"],
                    "distinct_id": event["distinct_id"],
                },
            )

        res = sync_execute(
            SELECT_LIVE_EVENTS_BY_TEAM_AND_CONDITIONS_SQL.format(
                database=CLICKHOUSE_DATABASE, conditions="", order="ASC", limit="LIMIT 3"
            ),
            {"team_id": 1},
        )

        event1 = res[0]
        event2 = res[1]
        event3 = res[2]

        self.assertEqual(event1[1], "event1")
        self.assertEqual(event2[1], "event2")
        self.assertEqual(event3[1], "event3")

        self.assertEqual(event1[3], "some-distinct-id")
        self.assertEqual(event2[3], "some-distinct-id")
        self.assertEqual(event3[3], "some-distinct-id")

        self.assertEqual(event1[7], "events")
        self.assertEqual(event2[7], "events")
        self.assertEqual(event3[7], "events")

    def test_all_events_on_live_events_table(self):

        # create all events *only* on the live_events table
        for event in events:
            sync_execute(
                INSERT_INTO_LIVE_EVENTS_SQL,
                {
                    "uuid": event["uuid"],
                    "event": event["event"],
                    "properties": json.dumps(event["properties"]),
                    "timestamp": event["timestamp"],
                    "team_id": event["team_id"],
                    "distinct_id": event["distinct_id"],
                },
            )

        res = sync_execute(
            SELECT_LIVE_EVENTS_BY_TEAM_AND_CONDITIONS_SQL.format(
                database=CLICKHOUSE_DATABASE, conditions="", order="ASC", limit="LIMIT 3"
            ),
            {"team_id": 1},
        )

        event1 = res[0]
        event2 = res[1]
        event3 = res[2]

        self.assertEqual(event1[1], "event1")
        self.assertEqual(event2[1], "event2")
        self.assertEqual(event3[1], "event3")

        self.assertEqual(event1[3], "some-distinct-id")
        self.assertEqual(event2[3], "some-distinct-id")
        self.assertEqual(event3[3], "some-distinct-id")

        self.assertEqual(event1[4], '{"foo": "bar"}')
        self.assertEqual(event2[4], '{"foo": "bar"}')
        self.assertEqual(event3[4], '{"foo": "bar"}')

        self.assertEqual(event1[7], "live_events")
        self.assertEqual(event2[7], "live_events")
        self.assertEqual(event3[7], "live_events")

    def test_all_events_on_events_table(self):

        # create all events *only* on the events table
        for event in events:
            _create_event(
                event_uuid=event["uuid"],
                event=event["event"],
                properties=event["properties"],
                timestamp=event["timestamp"],
                team_id=event["team_id"],
                distinct_id=event["distinct_id"],
            )

        res = sync_execute(
            SELECT_LIVE_EVENTS_BY_TEAM_AND_CONDITIONS_SQL.format(
                database=CLICKHOUSE_DATABASE, conditions="", order="ASC", limit="LIMIT 3"
            ),
            {"team_id": 1},
        )

        event1 = res[0]
        event2 = res[1]
        event3 = res[2]

        self.assertEqual(event1[1], "event1")
        self.assertEqual(event2[1], "event2")
        self.assertEqual(event3[1], "event3")

        self.assertEqual(event1[3], "some-distinct-id")
        self.assertEqual(event2[3], "some-distinct-id")
        self.assertEqual(event3[3], "some-distinct-id")

        self.assertEqual(event1[4], '{"foo": "bar"}')
        self.assertEqual(event2[4], '{"foo": "bar"}')
        self.assertEqual(event3[4], '{"foo": "bar"}')

        self.assertEqual(event1[7], "events")
        self.assertEqual(event2[7], "events")
        self.assertEqual(event3[7], "events")

    def test_create_some_events_on_each_table(self):

        # create event1 and event2 events *only* on the events table
        # and event3 *only* on the live events table

        _create_event(
            event_uuid=events[0]["uuid"],
            event=events[0]["event"],
            properties=events[0]["properties"],
            timestamp=events[0]["timestamp"],
            team_id=events[0]["team_id"],
            distinct_id=events[0]["distinct_id"],
        )

        _create_event(
            event_uuid=events[1]["uuid"],
            event=events[1]["event"],
            properties=events[1]["properties"],
            timestamp=events[1]["timestamp"],
            team_id=events[1]["team_id"],
            distinct_id=events[1]["distinct_id"],
        )

        sync_execute(
            INSERT_INTO_LIVE_EVENTS_SQL,
            {
                "uuid": events[2]["uuid"],
                "event": events[2]["event"],
                "properties": json.dumps(events[2]["properties"]),
                "timestamp": events[2]["timestamp"],
                "team_id": events[2]["team_id"],
                "distinct_id": events[2]["distinct_id"],
            },
        )

        res = sync_execute(
            SELECT_LIVE_EVENTS_BY_TEAM_AND_CONDITIONS_SQL.format(
                database=CLICKHOUSE_DATABASE, conditions="", order="ASC", limit="LIMIT 3"
            ),
            {"team_id": 1},
        )

        event1 = res[0]
        event2 = res[1]
        event3 = res[2]

        self.assertEqual(event1[1], "event1")
        self.assertEqual(event2[1], "event2")
        self.assertEqual(event3[1], "event3")

        self.assertEqual(event1[3], "some-distinct-id")
        self.assertEqual(event2[3], "some-distinct-id")
        self.assertEqual(event3[3], "some-distinct-id")

        self.assertEqual(event1[4], '{"foo": "bar"}')
        self.assertEqual(event2[4], '{"foo": "bar"}')
        self.assertEqual(event3[4], '{"foo": "bar"}')

        self.assertEqual(event1[7], "events")
        self.assertEqual(event2[7], "events")
        self.assertEqual(event3[7], "live_events")
