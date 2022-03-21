from datetime import timedelta
from uuid import uuid4

from freezegun.api import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.group import create_group
from ee.clickhouse.queries.stickiness.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.api.test.test_stickiness import get_stickiness_time_series_ok, stickiness_test_factory
from posthog.api.test.test_trends import get_people_from_url_ok
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
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
        p1, p2, p3, p4 = self._create_multiple_people(
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
            data = get_stickiness_time_series_ok(
                client=self.client,
                team=self.team,
                request={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-02-15",
                    "events": [{"id": "watched movie"}],
                    "properties": [{"key": "industry", "value": "technology", "type": "group", "group_type_index": 0}],
                    "interval": "week",
                },
            )

        assert data["watched movie"][1].value == 1
        assert data["watched movie"][2].value == 0
        assert data["watched movie"][3].value == 1

        with freeze_time("2020-02-15T13:01:01Z"):
            week1_actors = get_people_from_url_ok(self.client, data["watched movie"][1].person_url)
            week2_actors = get_people_from_url_ok(self.client, data["watched movie"][2].person_url)
            week3_actors = get_people_from_url_ok(self.client, data["watched movie"][3].person_url)

        assert sorted([p["id"] for p in week1_actors]) == sorted([str(p1.pk)])
        assert sorted([p["id"] for p in week2_actors]) == sorted([])
        assert sorted([p["id"] for p in week3_actors]) == sorted([str(p3.pk)])

    @snapshot_clickhouse_queries
    def test_aggregate_by_groups(self):
        self._create_multiple_people(
            period=timedelta(weeks=1), event_properties=lambda i: {"$group_0": f"org:{i // 2}"},
        )

        create_group(
            team_id=self.team.pk, group_type_index=0, group_key=f"org:0", properties={"industry": "technology"}
        )
        create_group(
            team_id=self.team.pk, group_type_index=0, group_key=f"org:1", properties={"industry": "agriculture"}
        )
        create_group(
            team_id=self.team.pk, group_type_index=0, group_key=f"org:2", properties={"industry": "technology"}
        )

        with freeze_time("2020-02-15T13:01:01Z"):
            data = get_stickiness_time_series_ok(
                client=self.client,
                team=self.team,
                request={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-02-15",
                    "events": [{"id": "watched movie", "math": "unique_group", "math_group_type_index": 0}],
                    "interval": "week",
                },
            )

        assert data["watched movie"][1].value == 2
        assert data["watched movie"][2].value == 0
        assert data["watched movie"][3].value == 1

        with freeze_time("2020-02-15T13:01:01Z"):
            week1_actors = get_people_from_url_ok(self.client, data["watched movie"][1].person_url)
            week2_actors = get_people_from_url_ok(self.client, data["watched movie"][2].person_url)
            week3_actors = get_people_from_url_ok(self.client, data["watched movie"][3].person_url)

        assert sorted([p["id"] for p in week1_actors]) == sorted(["org:0", "org:2"])
        assert sorted([p["id"] for p in week2_actors]) == sorted([])
        assert sorted([p["id"] for p in week3_actors]) == sorted(["org:1"])
