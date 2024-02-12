import json
from datetime import datetime
from uuid import UUID

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from freezegun.api import freeze_time
from unittest.case import skip

from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.queries.trends.trends_actors import TrendsActors
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)


class TestPerson(ClickhouseTestMixin, APIBaseTest):
    # Note: not using `@snapshot_clickhouse_queries` here because the ordering of the session_ids in the recording
    # query is not guaranteed, so adding it would lead to a flaky test.
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_person_query_includes_recording_events(self):
        _create_person(team_id=self.team.pk, distinct_ids=["u1"], properties={"email": "bla"})
        _create_event(
            event="pageview", distinct_id="u1", team=self.team, timestamp=timezone.now()
        )  # No $session_id, so not included
        _create_event(
            event="pageview",
            distinct_id="u1",
            team=self.team,
            timestamp=timezone.now(),
            properties={"$session_id": "s2", "$window_id": "w2"},
        )  # No associated recording, so not included
        timestamp = timezone.now()
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            distinct_id="u1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        _create_event(
            event="pageview",
            distinct_id="u1",
            team=self.team,
            timestamp=timezone.now() + relativedelta(hours=2),
            properties={"$session_id": "s1", "$window_id": "w1"},
            event_uuid="b06e5a5e-e001-4293-af81-ac73e194569d",
        )
        _create_event(
            event="pageview",
            distinct_id="u1",
            team=self.team,
            timestamp=timezone.now() + relativedelta(hours=3),
            properties={"$session_id": "s1", "$window_id": "w1"},
            event_uuid="206e5a5e-e001-4293-af81-ac73e194569d",
        )
        event = {"id": "pageview", "name": "pageview", "type": "events", "order": 0}
        filter = Filter(
            data={
                "date_from": "2021-01-21T00:00:00Z",
                "date_to": "2021-01-21T23:59:59Z",
                "events": [event],
                "include_recordings": "true",
            }
        )
        entity = Entity(event)

        _, serialized_actors, _ = TrendsActors(self.team, entity, filter).get_actors()
        self.assertEqual(len(serialized_actors), 1)
        self.assertEqual(len(serialized_actors[0]["matched_recordings"]), 1)
        self.assertEqual(serialized_actors[0]["matched_recordings"][0]["session_id"], "s1")
        self.assertCountEqual(
            serialized_actors[0]["matched_recordings"][0]["events"],
            [
                {
                    "window_id": "w1",
                    "timestamp": timezone.now() + relativedelta(hours=3),
                    "uuid": UUID("206e5a5e-e001-4293-af81-ac73e194569d"),
                },
                {
                    "window_id": "w1",
                    "timestamp": timezone.now() + relativedelta(hours=2),
                    "uuid": UUID("b06e5a5e-e001-4293-af81-ac73e194569d"),
                },
            ],
        )

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_person_query_does_not_include_recording_events_if_flag_not_set(self):
        _create_person(team_id=self.team.pk, distinct_ids=["u1"], properties={"email": "bla"})
        _create_event(event="pageview", distinct_id="u1", team=self.team, timestamp=timezone.now())

        event = {"id": "pageview", "name": "pageview", "type": "events", "order": 0}
        filter = Filter(
            data={
                "date_from": "2021-01-21T00:00:00Z",
                "date_to": "2021-01-21T23:59:59Z",
                "events": [event],
            }
        )
        entity = Entity(event)
        _, serialized_actors, _ = TrendsActors(self.team, entity, filter).get_actors()

        self.assertEqual(serialized_actors[0].get("matched_recordings"), [])

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_group_query_includes_recording_events(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        create_group(team_id=self.team.pk, group_type_index=0, group_key="bla", properties={})
        timestamp = timezone.now()
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            distinct_id="u1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        _create_event(
            event="pageview",
            distinct_id="u1",
            team=self.team,
            timestamp=timezone.now(),
            properties={"$group_0": "bla"},
        )
        _create_event(
            event="pageview",
            distinct_id="u1",
            team=self.team,
            timestamp=timezone.now() + relativedelta(hours=2),
            properties={"$session_id": "s1", "$window_id": "w1", "$group_0": "bla"},
            event_uuid="b06e5a5e-e001-4293-af81-ac73e194569d",
        )

        event = {
            "id": "pageview",
            "name": "pageview",
            "type": "events",
            "order": 0,
            "math": "unique_group",
            "math_group_type_index": 0,
        }

        filter = Filter(
            data={
                "date_from": "2021-01-21T00:00:00Z",
                "date_to": "2021-01-21T23:59:59Z",
                "events": [event],
                "include_recordings": "true",
            }
        )
        entity = Entity(event)

        _, serialized_actors, _ = TrendsActors(self.team, entity, filter).get_actors()

        self.assertCountEqual(
            serialized_actors[0].get("matched_recordings", []),
            [
                {
                    "session_id": "s1",
                    "events": [
                        {
                            "window_id": "w1",
                            "timestamp": timezone.now() + relativedelta(hours=2),
                            "uuid": UUID("b06e5a5e-e001-4293-af81-ac73e194569d"),
                        }
                    ],
                }
            ],
        )


class TestPersonIntegration(ClickhouseTestMixin, APIBaseTest):
    def test_weekly_active_users(self):
        for d in range(10, 18):  # create a person and event for each day 10. Sep - 17. Sep
            _create_person(team_id=self.team.pk, distinct_ids=[f"u_{d}"])
            _create_event(
                event="pageview",
                distinct_id=f"u_{d}",
                team=self.team,
                timestamp=datetime(2023, 9, d, 00, 42),
            )
        flush_persons_and_events()

        # request weekly active users in the following week
        filter = {
            "insight": "TRENDS",
            "date_from": "2023-09-17T13:37:00",
            "date_to": "2023-09-24T13:37:00",
            "events": json.dumps([{"id": "pageview", "math": "weekly_active"}]),
        }
        insight_response = self.client.get(f"/api/projects/{self.team.pk}/insights/trend", data=filter)
        insight_response = (insight_response.json()).get("result")

        self.assertEqual(insight_response[0].get("labels")[5], "22-Sep-2023")
        self.assertEqual(insight_response[0].get("data")[5], 2)

        persons_url = insight_response[0].get("persons_urls")[5].get("url")
        response = self.client.get("/" + persons_url)

        data = response.json()
        self.assertEqual(data.get("results")[0].get("count"), 2)
        self.assertEqual(
            [item["name"] for item in data.get("results")[0].get("people")],
            ["u_17", "u_16"],
        )

    def test_weekly_active_users_grouped_by_week(self):
        for d in range(10, 18):  # create a person and event for each day 10. Sep - 17. Sep
            _create_person(team_id=self.team.pk, distinct_ids=[f"u_{d}"])
            _create_event(
                event="pageview",
                distinct_id=f"u_{d}",
                team=self.team,
                timestamp=datetime(2023, 9, d, 00, 42),
            )
        flush_persons_and_events()

        # request weekly active users in the following week
        filter = {
            "insight": "TRENDS",
            "date_from": "2023-09-17T13:37:00",
            "date_to": "2023-09-24T13:37:00",
            "interval": "week",
            "events": json.dumps([{"id": "pageview", "math": "weekly_active"}]),
        }
        insight_response = self.client.get(f"/api/projects/{self.team.pk}/insights/trend", data=filter)
        insight_response = (insight_response.json()).get("result")

        self.assertEqual(insight_response[0].get("labels")[0], "17-Sep-2023")
        self.assertEqual(insight_response[0].get("data")[0], 7)

        persons_url = insight_response[0].get("persons_urls")[0].get("url")
        response = self.client.get("/" + persons_url)

        data = response.json()
        self.assertEqual(data.get("results")[0].get("count"), 7)
        self.assertEqual(
            [item["name"] for item in data.get("results")[0].get("people")],
            ["u_17", "u_16", "u_15", "u_14", "u_13", "u_12", "u_11"],
        )

    def test_weekly_active_users_cumulative(self):
        for d in range(10, 18):  # create a person and event for each day 10. Sep - 17. Sep
            _create_person(team_id=self.team.pk, distinct_ids=[f"u_{d}"])
            _create_event(
                event="pageview",
                distinct_id=f"u_{d}",
                team=self.team,
                timestamp=datetime(2023, 9, d, 00, 42),
            )
        flush_persons_and_events()

        # request weekly active users in the following week
        filter = {
            "insight": "TRENDS",
            "date_from": "2023-09-10T13:37:00",
            "date_to": "2023-09-24T13:37:00",
            "events": json.dumps([{"id": "pageview", "math": "weekly_active"}]),
            "display": "ActionsLineGraphCumulative",
        }
        insight_response = self.client.get(f"/api/projects/{self.team.pk}/insights/trend", data=filter)
        insight_response = (insight_response.json()).get("result")

        self.assertEqual(insight_response[0].get("labels")[1], "11-Sep-2023")
        self.assertEqual(insight_response[0].get("data")[1], 3)

        persons_url = insight_response[0].get("persons_urls")[1].get("url")
        response = self.client.get("/" + persons_url)

        data = response.json()
        self.assertEqual(data.get("results")[0].get("count"), 2)
        self.assertEqual(
            [item["name"] for item in data.get("results")[0].get("people")],
            ["u_11", "u_10"],
        )

    @skip("see PR 17356")
    def test_weekly_active_users_breakdown(self):
        for d in range(10, 18):  # create a person and event for each day 10. Sep - 17. Sep
            _create_person(team_id=self.team.pk, distinct_ids=[f"a_{d}"])
            _create_person(team_id=self.team.pk, distinct_ids=[f"b_{d}"])
            _create_event(
                event="pageview",
                distinct_id=f"a_{d}",
                properties={"some_prop": "a"},
                team=self.team,
                timestamp=datetime(2023, 9, d, 00, 42),
            )
            _create_event(
                event="pageview",
                distinct_id=f"b_{d}",
                properties={"some_prop": "b"},
                team=self.team,
                timestamp=datetime(2023, 9, d, 00, 42),
            )
        flush_persons_and_events()

        # request weekly active users in the following week
        filter = {
            "insight": "TRENDS",
            "date_from": "2023-09-17T13:37:00",
            "date_to": "2023-09-24T13:37:00",
            "events": json.dumps([{"id": "pageview", "math": "weekly_active"}]),
            "breakdown": "some_prop",
        }
        insight_response = self.client.get(f"/api/projects/{self.team.pk}/insights/trend", data=filter)
        insight_response = (insight_response.json()).get("result")

        self.assertEqual(insight_response[0].get("labels")[5], "22-Sep-2023")
        # self.assertEqual(insight_response[0].get("data")[5], 2)

        persons_url = insight_response[0].get("persons_urls")[5].get("url")
        response = self.client.get("/" + persons_url)

        data = response.json()
        # self.assertEqual(data.get("results")[0].get("count"), 2)
        self.assertEqual(
            [item["name"] for item in data.get("results")[0].get("people")],
            ["a_17", "a_16"],
        )
