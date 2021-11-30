from datetime import timedelta
from uuid import uuid4

from freezegun.api import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.group import create_group
from ee.clickhouse.queries.stickiness.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.api.test.test_stickiness import get_stickiness_ok, stickiness_test_factory
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.person import Person


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    event_name = kwargs.pop("event_name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=event_name)
    return action


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class TestClickhouseStickiness(ClickhouseTestMixin, stickiness_test_factory(ClickhouseStickiness, _create_event, _create_person, _create_action, get_earliest_timestamp)):  # type: ignore
    @snapshot_clickhouse_queries
    def test_filter_by_group_properties(self):
        self._create_multiple_people(
            period=timedelta(weeks=1), event_properties=lambda i: {"$group_0": f"org:{i}", "$group_1": "instance:1"},
        )
        create_group(
            team_id=self.team.pk, group_type_index=0, group_key=f"org:1", properties={"industry": "technology"}
        )
        create_group(
            team_id=self.team.pk, group_type_index=0, group_key=f"org:2", properties={"industry": "agriculture"}
        )
        create_group(
            team_id=self.team.pk, group_type_index=0, group_key=f"org:3", properties={"industry": "technology"}
        )
        create_group(
            team_id=self.team.pk, group_type_index=1, group_key=f"company:1", properties={"industry": "technology"}
        )

        with freeze_time("2020-02-15T13:01:01Z"):
            stickiness_response = get_stickiness_ok(
                client=self.client,
                team_id=self.team.pk,
                request={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-02-15",
                    "events": [{"id": "watched movie"}],
                    "properties": [{"key": "industry", "value": "technology", "type": "group", "group_type_index": 0}],
                    "interval": "week",
                },
            )

            response = stickiness_response["result"]

        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["data"][0], 1)
        self.assertEqual(response[0]["data"][1], 0)
        self.assertEqual(response[0]["data"][2], 1)

    @snapshot_clickhouse_queries
    def test_aggregate_by_groups(self):
        self._create_multiple_people(
            period=timedelta(weeks=1), event_properties=lambda i: {"$group_0": f"org:{i // 2}"},
        )

        with freeze_time("2020-02-15T13:01:01Z"):
            stickiness_response = get_stickiness_ok(
                client=self.client,
                team_id=self.team.pk,
                request={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-02-15",
                    "events": [{"id": "watched movie"}],
                    "interval": "week",
                },
            )

            response = stickiness_response["result"]

        self.assertEqual(response[0]["count"], 4)
        self.assertEqual(response[0]["data"][0], 2)
        self.assertEqual(response[0]["data"][1], 1)
        self.assertEqual(response[0]["data"][2], 1)
        self.assertEqual(response[0]["data"][6], 0)
