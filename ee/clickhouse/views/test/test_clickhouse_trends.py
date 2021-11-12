from datetime import datetime
from uuid import uuid4

from freezegun.api import freeze_time

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.util import deep_dump_object
from ee.clickhouse.test.test_journeys import journeys_for
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


class ClickhouseTestInsights(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    @snapshot_clickhouse_queries
    def test_insight_trends_basic(self):

        events_by_person = {
            "1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)},],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)},],
        }
        created_people = journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):

            request = TrendsRequest(
                date_from="-14d",
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

        assert sorted([p["id"] for p in people]) == sorted(
            [str(created_people["1"].uuid), str(created_people["2"].uuid)]
        )

    @snapshot_clickhouse_queries
    def test_insight_trends_aggregate(self):

        events_by_person = {
            "1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 13, 3)},],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)},],
        }
        created_people = journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
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

        assert sorted([p["id"] for p in people]) == sorted(
            [str(created_people["1"].uuid), str(created_people["2"].uuid)]
        )

    @snapshot_clickhouse_queries
    def test_insight_trends_cumulative(self):

        events_by_person = {
            "p1": [
                {"event": "$pageview", "timestamp": datetime(2012, 1, 13, 3), "properties": {"key": "val"}},
                {"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3), "properties": {"key": "val"}},
            ],
            "p2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 13, 3), "properties": {"key": "notval"}},],
            "p3": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3), "properties": {"key": "val"}},],
        }
        created_people = journeys_for(events_by_person, self.team)

        # Total Volume
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
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

        assert sorted([p["id"] for p in person_response]) == sorted(
            [str(created_people["p1"].uuid), str(created_people["p2"].uuid), str(created_people["p3"].uuid)]
        )

        # DAU

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-14d",
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

        assert sorted([p["id"] for p in person_response]) == sorted(
            [str(created_people["p1"].uuid), str(created_people["p2"].uuid), str(created_people["p3"].uuid)]
        )

        # breakdown
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
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

        assert sorted([p["id"] for p in person_response]) == sorted(
            [str(created_people["p1"].uuid), str(created_people["p3"].uuid)]
        )

        # breakdown dau
        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequestBreakdown(
                date_from="-14d",
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

        assert sorted([p["id"] for p in people]) == sorted(
            [str(created_people["p1"].uuid), str(created_people["p3"].uuid)]
        )

    @test_with_materialized_columns(["key"])
    def test_breakdown_with_filter(self):
        events_by_person = {
            "person1": [{"event": "sign up", "timestamp": datetime(2012, 1, 13, 3), "properties": {"key": "val"}},],
            "person2": [{"event": "sign up", "timestamp": datetime(2012, 1, 13, 3), "properties": {"key": "oh"}},],
        }
        created_people = journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            params = TrendsRequestBreakdown(
                date_from="-14d",
                breakdown="key",
                events=[{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                properties=[{"key": "key", "value": "oh", "operator": "not_icontains"}],
            )
            data_response = get_trends_time_series_ok(self.client, params, self.team)
            person_response = get_trends_people_ok(self.client, data_response["sign up - val"]["2012-01-13"].person_url)

        assert data_response["sign up - val"]["2012-01-13"].value == 1
        assert data_response["sign up - val"]["2012-01-13"].breakdown_value == "val"

        assert sorted([p["id"] for p in person_response]) == sorted([str(created_people["person1"].uuid)])

        with freeze_time("2012-01-15T04:01:34.000Z"):
            params = TrendsRequestBreakdown(
                date_from="-14d",
                breakdown="key",
                display="ActionsPie",
                events=[{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
            )
            aggregate_response = get_trends_aggregate_ok(self.client, params, self.team)
            aggregate_person_response = get_trends_people_ok(
                self.client, aggregate_response["sign up - val"].person_url
            )

        assert aggregate_response["sign up - val"].value == 1
        assert sorted([p["id"] for p in aggregate_person_response]) == sorted([str(created_people["person1"].uuid)])

    def test_insight_trends_compare(self):
        events_by_person = {
            "p1": [
                {"event": "$pageview", "timestamp": datetime(2012, 1, 5, 3), "properties": {"key": "val"}},
                {"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3), "properties": {"key": "val"}},
            ],
            "p2": [
                {"event": "$pageview", "timestamp": datetime(2012, 1, 5, 3), "properties": {"key": "notval"}},
                {"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3), "properties": {"key": "notval"}},
            ],
        }
        created_people = journeys_for(events_by_person, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):
            request = TrendsRequest(
                date_from="-7d",
                compare=True,
                events=[{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0,}],
            )
            data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["$pageview - current"]["2012-01-13"].value == 0
        assert data_response["$pageview - current"]["2012-01-14"].value == 2

        assert data_response["$pageview - previous"]["2012-01-04"].value == 0
        assert data_response["$pageview - previous"]["2012-01-05"].value == 2

        with freeze_time("2012-01-15T04:01:34.000Z"):
            curr_people = get_trends_people_ok(
                self.client, data_response["$pageview - current"]["2012-01-14"].person_url
            )
            prev_people = get_trends_people_ok(
                self.client, data_response["$pageview - previous"]["2012-01-05"].person_url
            )

        assert sorted([p["id"] for p in curr_people]) == sorted(
            [str(created_people["p1"].uuid), str(created_people["p2"].uuid)]
        )
        assert sorted([p["id"] for p in prev_people]) == sorted(
            [str(created_people["p1"].uuid), str(created_people["p2"].uuid)]
        )
