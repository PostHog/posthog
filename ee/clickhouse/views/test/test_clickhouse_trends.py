from uuid import uuid4

from freezegun.api import freeze_time

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.util import deep_dump_object
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.api.test.test_insight import insight_test_factory
from posthog.api.test.test_trends import (
    TrendsRequest,
    TrendsRequestBreakdown,
    get_trends_aggregate_ok,
    get_trends_people_ok,
    get_trends_time_series_ok,
)
from posthog.models.person import Person
from posthog.test.base import APIBaseTest, test_with_materialized_columns


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=str(person.uuid))


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class ClickhouseTestInsights(
    ClickhouseTestMixin, LicensedTestMixin, APIBaseTest  # type: ignore
):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    @snapshot_clickhouse_queries
    def test_insight_trends_basic(self):
        with freeze_time("2012-01-14T03:21:34.000Z"):
            p1 = _create_person(distinct_ids=["1"], team=self.team)
            p2 = _create_person(distinct_ids=["2"], team=self.team)
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            _create_event(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):

            request = TrendsRequest(
                date_from="-14d",
                date_to="2012-01-15",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        assert data["$pageview"]["2012-01-13"].value == 0
        assert data["$pageview"]["2012-01-14"].value == 2
        assert data["$pageview"]["2012-01-14"].label == "14-Jan-2012"
        assert data["$pageview"]["2012-01-15"].value == 0

        with freeze_time("2012-01-15T04:01:34.000Z"):
            people = get_trends_people_ok(self.client, data["$pageview"]["2012-01-14"].person_url)

        assert sorted([p["id"] for p in people]) == sorted([p1.pk, p2.pk])

    @snapshot_clickhouse_queries
    def test_insight_trends_aggregate(self):

        with freeze_time("2012-01-13T03:21:34.000Z"):
            p1 = _create_person(distinct_ids=["1"], team=self.team)
            _create_event(team=self.team, event="$pageview", distinct_id="1")

        with freeze_time("2012-01-14T03:21:34.000Z"):
            p2 = _create_person(distinct_ids=["2"], team=self.team)
            _create_event(team=self.team, event="$pageview", distinct_id="2")

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                date_to="2012-01-15",
                interval="day",
                insight="TRENDS",
                display="ActionsPie",
                events=[
                    {
                        "id": "$pageview",
                        "math": None,
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data = get_trends_aggregate_ok(self.client, request, self.team)

        assert data["$pageview"].value == 2
        assert data["$pageview"].label == "$pageview"

        with freeze_time("2012-01-15T04:01:34.000Z"):
            people = get_trends_people_ok(self.client, data["$pageview"].person_url)

        assert sorted([p["id"] for p in people]) == sorted([p1.pk, p2.pk])

    @snapshot_clickhouse_queries
    def test_insight_trends_cumulative(self):
        with freeze_time("2012-01-13T03:21:34.000Z"):
            p1 = _create_person(distinct_ids=["1"], team=self.team)
            p2 = _create_person(distinct_ids=["2"], team=self.team)
            _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"key": "val"})
            _create_event(team=self.team, event="$pageview", distinct_id="2", properties={"key": "notval"})

        with freeze_time("2012-01-14T03:21:34.000Z"):
            p3 = _create_person(distinct_ids=["3"], team=self.team)
            _create_event(team=self.team, event="$pageview", distinct_id="3", properties={"key": "val"})
            _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"key": "val"})

        # Total Volume
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                date_to="2012-01-15",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraphCumulative",
                events=[
                    {
                        "id": "$pageview",
                        "math": None,
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)
            person_response = get_trends_people_ok(self.client, data_response["$pageview"]["2012-01-14"].person_url)

        assert data_response["$pageview"]["2012-01-13"].value == 2
        assert data_response["$pageview"]["2012-01-14"].value == 4
        assert data_response["$pageview"]["2012-01-15"].value == 4
        assert data_response["$pageview"]["2012-01-14"].label == "14-Jan-2012"

        assert sorted([p["id"] for p in person_response]) == sorted([p1.pk, p2.pk, p3.pk])

        # DAU

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
                date_to="2012-01-15",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraphCumulative",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)
            person_response = get_trends_people_ok(self.client, data_response["$pageview"]["2012-01-14"].person_url)

        assert data_response["$pageview"]["2012-01-13"].value == 2
        assert data_response["$pageview"]["2012-01-14"].value == 3
        assert data_response["$pageview"]["2012-01-15"].value == 3
        assert data_response["$pageview"]["2012-01-14"].label == "14-Jan-2012"

        assert sorted([p["id"] for p in person_response]) == sorted([p1.pk, p2.pk, p3.pk])

        # breakdown
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                date_to="2012-01-15",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraphCumulative",
                breakdown="key",
                breakdown_type="event",
                events=[
                    {
                        "id": "$pageview",
                        "math": None,
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)
            person_response = get_trends_people_ok(
                self.client, data_response["$pageview - val"]["2012-01-14"].person_url
            )

        assert data_response["$pageview - val"]["2012-01-13"].value == 1
        assert data_response["$pageview - val"]["2012-01-13"].breakdown_value == "val"
        assert data_response["$pageview - val"]["2012-01-14"].value == 3
        assert data_response["$pageview - val"]["2012-01-14"].label == "14-Jan-2012"

        assert sorted([p["id"] for p in person_response]) == sorted([p1.pk, p3.pk])

        # breakdown dau
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
                date_to="2012-01-15",
                interval="day",
                insight="TRENDS",
                display="ActionsLineGraphCumulative",
                breakdown="key",
                breakdown_type="event",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)
            people = get_trends_people_ok(self.client, data_response["$pageview - val"]["2012-01-14"].person_url)

        assert data_response["$pageview - val"]["2012-01-13"].value == 1
        assert data_response["$pageview - val"]["2012-01-13"].breakdown_value == "val"
        assert data_response["$pageview - val"]["2012-01-14"].value == 2
        assert data_response["$pageview - val"]["2012-01-14"].label == "14-Jan-2012"

        assert sorted([p["id"] for p in people]) == sorted([p1.pk, p3.pk])

    @test_with_materialized_columns(["key"])
    def test_breakdown_with_filter(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"email": "test@posthog.com"})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "test@gmail.com"})
        _create_event(event="sign up", distinct_id="person1", team=self.team, properties={"key": "val"})
        _create_event(event="sign up", distinct_id="person2", team=self.team, properties={"key": "oh"})

        data = deep_dump_object(
            {
                "date_from": "-14d",
                "breakdown": "key",
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                "properties": [{"key": "key", "value": "oh", "operator": "not_icontains"}],
            }
        )
        response = self.client.get(f"/api/projects/{self.team.id}/insights/trend/", data=data).json()

        self.assertEqual(response["result"][0]["count"], 1)
        # don't return none option when empty
        self.assertEqual(response["result"][0]["breakdown_value"], "val")
        person_response = self.client.get("/" + response["result"][0]["persons_urls"][-1]["url"]).json()
        self.assertEqual(len(person_response["results"][0]["people"]), 1)

        data = deep_dump_object(
            {
                "date_from": "-14d",
                "breakdown": "key",
                "display": "ActionsPie",
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
            }
        )
        response = self.client.get(f"/api/projects/{self.team.id}/insights/trend/", data=data).json()

        self.assertEqual(response["result"][0]["aggregated_value"], 1)

        person_response = self.client.get("/" + response["result"][0]["persons"]["url"]).json()
        self.assertEqual(len(person_response["results"][0]["people"]), 1)

    def test_insight_trends_compare(self):
        with freeze_time("2012-01-05T03:21:34.000Z"):
            _create_person(distinct_ids=["1"], team=self.team)
            _create_person(distinct_ids=["2"], team=self.team)
            _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"key": "val"})
            _create_event(team=self.team, event="$pageview", distinct_id="2", properties={"key": "notval"})

        with freeze_time("2012-01-14T03:21:34.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"key": "val"})
            _create_event(team=self.team, event="$pageview", distinct_id="2", properties={"key": "notval"})

        with freeze_time("2012-01-15T04:01:34.000Z"):
            data = deep_dump_object(
                {
                    "date_from": "-7d",
                    "compare": True,
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0,}],
                }
            )
            response = self.client.get(f"/api/projects/{self.team.id}/insights/trend/", data=data).json()

        self.assertEqual(response["result"][0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0])
        self.assertEqual(response["result"][1]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0])

        with freeze_time("2012-01-15T04:01:34.000Z"):
            first_series_response = self.client.get("/" + response["result"][0]["persons_urls"][-2]["url"]).json()
            second_series_response = self.client.get("/" + response["result"][1]["persons_urls"][-4]["url"]).json()
            zero_response = self.client.get("/" + response["result"][1]["persons_urls"][-1]["url"]).json()

        self.assertEqual(len(first_series_response["results"][0]["people"]), 2)
        self.assertEqual(len(second_series_response["results"][0]["people"]), 2)
        self.assertEqual(len(zero_response["results"][0]["people"]), 0)
