import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, Union

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, create_person_id_override_by_distinct_id, snapshot_clickhouse_queries

from django.test import override_settings
from django.test.client import Client

from dateutil.relativedelta import relativedelta

from posthog.clickhouse.client import sync_execute
from posthog.constants import ENTITY_ID, ENTITY_TYPE
from posthog.models.team import Team
from posthog.utils import encode_get_request_params


def get_stickiness(client: Client, team: Team, request: dict[str, Any]):
    return client.get(f"/api/projects/{team.pk}/insights/trend/", data=request)


def get_stickiness_ok(client: Client, team: Team, request: dict[str, Any]):
    response = get_stickiness(client=client, team=team, request=encode_get_request_params(data=request))
    assert response.status_code == 200, response.content
    return response.json()


def get_stickiness_time_series_ok(client: Client, team: Team, request: dict[str, Any]):
    data = get_stickiness_ok(client=client, request=request, team=team)
    return get_time_series_ok(data)


def get_stickiness_people(client: Client, team_id: int, request: dict[str, Any]):
    return client.get("/api/person/stickiness/", data=request)


def get_stickiness_people_ok(client: Client, team_id: int, request: dict[str, Any]):
    response = get_stickiness_people(client=client, team_id=team_id, request=encode_get_request_params(data=request))
    assert response.status_code == 200
    return response.json()


def get_time_series_ok(data):
    res = {}
    for item in data["result"]:
        collect_dates = {}
        for idx, date in enumerate(item["days"]):
            collect_dates[date] = NormalizedTrendResult(
                value=item["data"][idx],
                label=item["labels"][idx],
                breakdown_value=item.get("breakdown_value", None),
            )
        res[item["label"]] = collect_dates
    return res


@dataclass
class NormalizedTrendResult:
    value: float
    label: str
    breakdown_value: Optional[Union[str, int]]


# parameterize tests to reuse in EE
def stickiness_test_factory(stickiness, event_factory, person_factory, action_factory, get_earliest_timestamp):
    class TestStickiness(APIBaseTest):
        def _create_multiple_people(self, period=None, event_properties=lambda index: {}):
            if period is None:
                period = timedelta(days=1)
            base_time = datetime.fromisoformat("2020-01-01T12:00:00.000000")
            p1 = person_factory(
                team_id=self.team.id,
                distinct_ids=["person1"],
                properties={"name": "person1"},
            )
            p1_person_id = str(uuid.uuid4())
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person1",
                timestamp=base_time.replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Chrome", **event_properties(1)},
                person_id=p1_person_id,
            )

            p2 = person_factory(
                team_id=self.team.id,
                distinct_ids=["person2"],
                properties={"name": "person2"},
            )
            p2_person_id = str(uuid.uuid4())
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp=base_time.replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Chrome", **event_properties(2)},
                person_id=p2_person_id,
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp=(base_time + period).replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Chrome", **event_properties(2)},
                person_id=p2_person_id,
            )
            # same day
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp=(base_time + period).replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Chrome", **event_properties(2)},
                person_id=p2_person_id,
            )

            p3 = person_factory(
                team_id=self.team.id,
                distinct_ids=["person3a", "person3b"],
                properties={"name": "person3"},
            )
            p3_person_id = str(uuid.uuid4())
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3a",
                timestamp=(base_time).replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Chrome", **event_properties(3)},
                person_id=p3_person_id,
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3b",
                timestamp=(base_time + period).replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Chrome", **event_properties(3)},
                person_id=p3_person_id,
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3a",
                timestamp=(base_time + period * 2).replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Chrome", **event_properties(3)},
                person_id=p3_person_id,
            )

            p4 = person_factory(
                team_id=self.team.id,
                distinct_ids=["person4"],
                properties={"name": "person4"},
            )
            p4_person_id = str(uuid.uuid4())

            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person4",
                timestamp=(base_time + period * 4).replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Safari", **event_properties(4)},
                person_id=p4_person_id,
            )

            return p1, p2, p3, p4

        def test_stickiness(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "insight": "STICKINESS",
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": "watched movie"}],
                    },
                )

                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
        @snapshot_clickhouse_queries
        def test_stickiness_with_person_on_events_v2(self):
            # KLUDGE: We need to do this to ensure create_person_id_override_by_distinct_id
            # works correctly. Worth considering other approaches as we generally avoid
            # truncating tables in tests.
            sync_execute("TRUNCATE TABLE sharded_events")
            self._create_multiple_people()
            create_person_id_override_by_distinct_id("person1", "person2", self.team.pk)

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "insight": "STICKINESS",
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": "watched movie"}],
                    },
                )

                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 3)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 1)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        @snapshot_clickhouse_queries
        def test_stickiness_all_time(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "all",
                        "events": [{"id": "watched movie"}],
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        @snapshot_clickhouse_queries
        def test_stickiness_hours(self):
            self._create_multiple_people(period=timedelta(hours=1))

            with freeze_time("2020-01-01T20:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01T12:00:00.00Z",
                        "date_to": "2020-01-01T20:00:00.00Z",
                        "events": [{"id": "watched movie"}],
                        "interval": "hour",
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 hour")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 hours")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 hours")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 hours")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_weeks(self):
            self._create_multiple_people(period=timedelta(weeks=1))

            with freeze_time("2020-02-15T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
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
            self.assertEqual(response[0]["labels"][0], "1 week")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 weeks")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 weeks")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 weeks")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_months(self):
            self._create_multiple_people(period=relativedelta(months=1))

            with freeze_time("2020-02-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-09-08",
                        "events": [{"id": "watched movie"}],
                        "interval": "month",
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 month")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 months")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 months")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 months")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_prop_filter(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": "watched movie"}],
                        "properties": [{"key": "$browser", "value": "Chrome"}],
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 3)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 1)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_hogql_filter(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": "watched movie"}],
                        "properties": [
                            {
                                "key": "properties.$browser == 'Chrome' and like(person.properties.name, '%person%')",
                                "type": "hogql",
                            }
                        ],
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 3)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 1)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_entity_filter(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [
                            {
                                "id": "watched movie",
                                "properties": [{"key": "$browser", "value": "Chrome"}],
                            }
                        ],
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 3)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 1)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_any_event(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": None}],
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_entity_person_filter(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [
                            {
                                "id": "watched movie",
                                "properties": [
                                    {
                                        "key": "name",
                                        "value": ["person1"],
                                        "operator": "exact",
                                        "type": "person",
                                    }
                                ],
                            }
                        ],
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 1)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 1)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 0)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 0)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        def test_stickiness_action(self):
            self._create_multiple_people()
            watched_movie = action_factory(team=self.team, name="watch movie action", event_name="watched movie")

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "actions": [{"id": watched_movie.pk}],
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["label"], "watch movie action")
            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 day")

        @snapshot_clickhouse_queries
        def test_stickiness_people_endpoint(self):
            person1, _, _, person4 = self._create_multiple_people()

            watched_movie = action_factory(team=self.team, name="watch movie action", event_name="watched movie")

            stickiness_response = get_stickiness_people_ok(
                client=self.client,
                team_id=self.team.pk,
                request={
                    "shown_as": "Stickiness",
                    "stickiness_days": 1,
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-08",
                    "entity_id": watched_movie.id,
                    "entity_type": "actions",
                    "actions": [{"id": watched_movie.id, "type": "actions"}],
                },
            )
            people = stickiness_response["results"][0]["people"]

            all_people_ids = [str(person["id"]) for person in people]
            self.assertListEqual(sorted(all_people_ids), sorted([str(person1.uuid), str(person4.uuid)]))

        def test_stickiness_people_with_entity_filter(self):
            person1, _, _, _ = self._create_multiple_people()

            stickiness_response = get_stickiness_people_ok(
                client=self.client,
                team_id=self.team.pk,
                request={
                    "shown_as": "Stickiness",
                    "stickiness_days": 1,
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-08",
                    "events": [
                        {
                            "id": "watched movie",
                            "type": "events",
                            "properties": [{"key": "$browser", "value": "Chrome"}],
                        }
                    ],
                    "entity_id": "watched movie",
                },
            )
            people = stickiness_response["results"][0]["people"]

            self.assertEqual(len(people), 1)
            self.assertEqual(str(people[0]["id"]), str(person1.uuid))

        @snapshot_clickhouse_queries
        def test_stickiness_people_paginated(self):
            for i in range(150):
                person_name = f"person{i}"
                person_factory(
                    team_id=self.team.id,
                    distinct_ids=[person_name],
                    properties={"name": person_name},
                )
                event_factory(
                    team=self.team,
                    event="watched movie",
                    distinct_id=person_name,
                    timestamp="2020-01-01T12:00:00.00Z",
                    properties={"$browser": "Chrome"},
                )
            watched_movie = action_factory(team=self.team, name="watch movie action", event_name="watched movie")

            result = get_stickiness_people_ok(
                client=self.client,
                team_id=self.team.pk,
                request={
                    "shown_as": "Stickiness",
                    "stickiness_days": 1,
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-08",
                    ENTITY_TYPE: "actions",
                    ENTITY_ID: watched_movie.id,
                },
            )

            self.assertEqual(len(result["results"][0]["people"]), 100)

            second_result = self.client.get(result["next"]).json()
            self.assertEqual(len(second_result["results"][0]["people"]), 50)

        @snapshot_clickhouse_queries
        def test_compare(self):
            self._create_multiple_people()

            stickiness_response = get_stickiness_ok(
                client=self.client,
                team=self.team,
                request={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-08",
                    "compare": "true",
                    "display": "ActionsLineGraph",
                    "events": '[{"id":"watched movie","math":"dau","name":"watched movie","type":"events","order":null,"properties":[],"math_property":null}]',
                    "insight": "TRENDS",
                    "interval": "day",
                    "properties": "[]",
                    "shown_as": "Stickiness",
                },
            )
            response = stickiness_response["result"]
            self.assertEqual(response[0]["data"], [2, 1, 1, 0, 0, 0, 0, 0])
            self.assertEqual(response[1]["data"], [0, 0, 0, 0, 0, 0, 0, 0])

            self.assertEqual(response[0]["compare_label"], "current")
            self.assertEqual(response[1]["compare_label"], "previous")

        def test_filter_test_accounts(self):
            self._create_multiple_people()
            person_factory(
                team_id=self.team.id,
                distinct_ids=["ph"],
                properties={"email": "test@posthog.com"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="ph",
                timestamp=datetime.fromisoformat("2020-01-01T12:00:00.000000").replace(tzinfo=UTC).isoformat(),
                properties={"$browser": "Chrome"},
            )

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "2020-01-01",
                        "date_to": "2020-01-08",
                        "events": [{"id": "watched movie"}],
                        "filter_test_accounts": "true",
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

        @snapshot_clickhouse_queries
        def test_stickiness_all_time_with_sampling(self):
            self._create_multiple_people()

            with freeze_time("2020-01-08T13:01:01Z"):
                stickiness_response = get_stickiness_ok(
                    client=self.client,
                    team=self.team,
                    request={
                        "shown_as": "Stickiness",
                        "date_from": "all",
                        "events": [{"id": "watched movie"}],
                        "sampling_factor": 1,
                    },
                )
                response = stickiness_response["result"]

            self.assertEqual(response[0]["count"], 4)
            self.assertEqual(response[0]["labels"][0], "1 day")
            self.assertEqual(response[0]["data"][0], 2)
            self.assertEqual(response[0]["labels"][1], "2 days")
            self.assertEqual(response[0]["data"][1], 1)
            self.assertEqual(response[0]["labels"][2], "3 days")
            self.assertEqual(response[0]["data"][2], 1)
            self.assertEqual(response[0]["labels"][6], "7 days")
            self.assertEqual(response[0]["data"][6], 0)

    return TestStickiness
