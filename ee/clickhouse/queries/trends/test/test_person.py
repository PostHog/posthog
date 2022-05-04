from uuid import UUID, uuid4

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from freezegun.api import freeze_time

from ee.clickhouse.models.group import create_group
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.trends.person import ClickhouseTrendsActors
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.test.base import APIBaseTest, _create_event, _create_person


def _create_session_recording_event(team_id, distinct_id, session_id, timestamp, window_id="", has_full_snapshot=True):
    create_session_recording_event(
        uuid=uuid4(),
        team_id=team_id,
        distinct_id=distinct_id,
        timestamp=timestamp,
        session_id=session_id,
        window_id=window_id,
        snapshot_data={"timestamp": timestamp.timestamp(), "has_full_snapshot": has_full_snapshot,},
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
        _create_session_recording_event(
            self.team.pk, "u1", "s1", timestamp=timezone.now(),
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
        event = {
            "id": "pageview",
            "name": "pageview",
            "type": "events",
            "order": 0,
        }
        filter = Filter(
            data={
                "date_from": "2021-01-21T00:00:00Z",
                "date_to": "2021-01-22T00:00:00Z",
                "events": [event],
                "include_recordings": "true",
            }
        )
        entity = Entity(event)

        _, serialized_actors = ClickhouseTrendsActors(self.team, entity, filter).get_actors()
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

        event = {
            "id": "pageview",
            "name": "pageview",
            "type": "events",
            "order": 0,
        }
        filter = Filter(
            data={"date_from": "2021-01-21T00:00:00Z", "date_to": "2021-01-22T00:00:00Z", "events": [event],}
        )
        entity = Entity(event)
        _, serialized_actors = ClickhouseTrendsActors(self.team, entity, filter).get_actors()

        self.assertEqual(serialized_actors[0].get("matched_recordings"), None)

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_group_query_includes_recording_events(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        create_group(team_id=self.team.pk, group_type_index=0, group_key="bla", properties={})
        _create_session_recording_event(
            self.team.pk, "u1", "s1", timestamp=timezone.now(),
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
                "date_to": "2021-01-22T00:00:00Z",
                "events": [event],
                "include_recordings": "true",
            }
        )
        entity = Entity(event)

        _, serialized_actors = ClickhouseTrendsActors(self.team, entity, filter).get_actors()

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
