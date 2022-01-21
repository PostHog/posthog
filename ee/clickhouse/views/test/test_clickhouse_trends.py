from datetime import datetime

from freezegun.api import freeze_time

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.models.group import create_group
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.api.test.test_trends import (
    TrendsRequest,
    TrendsRequestBreakdown,
    get_people_from_url_ok,
    get_trends_aggregate_ok,
    get_trends_time_series_ok,
)
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.test.base import APIBaseTest, test_with_materialized_columns


class ClickhouseTestTrends(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
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
            people = get_people_from_url_ok(self.client, data["$pageview"]["2012-01-14"].person_url)

        assert sorted([p["id"] for p in people]) == sorted(
            [str(created_people["1"].uuid), str(created_people["2"].uuid)]
        )

    @snapshot_clickhouse_queries
    def test_insight_trends_clean_arg(self):

        events_by_actor = {
            "1": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3), "properties": {"key": "val"}},],
            "2": [{"event": "$pageview", "timestamp": datetime(2012, 1, 14, 3)},],
        }
        created_actors = journeys_for(events_by_actor, self.team)

        with freeze_time("2012-01-15T04:01:34.000Z"):

            request = TrendsRequest(
                date_from="-14d",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": None,  # this argument will now be removed from the request instead of becoming a string
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [{"key": "key", "value": "val"}],
                        "math_property": None,
                    }
                ],
            )
            data = get_trends_time_series_ok(self.client, request, self.team)

        actors = get_people_from_url_ok(self.client, data["$pageview"]["2012-01-14"].person_url)

        # this would return 2 people prior to #8103 fix
        # 'None' values have to be purged before formatting into the actor url
        assert sorted([p["id"] for p in actors]) == sorted([str(created_actors["1"].uuid)])

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
            people = get_people_from_url_ok(self.client, data["$pageview"].person_url)

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
            person_response = get_people_from_url_ok(self.client, data_response["$pageview"]["2012-01-14"].person_url)

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
            person_response = get_people_from_url_ok(self.client, data_response["$pageview"]["2012-01-14"].person_url)

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
            person_response = get_people_from_url_ok(
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
            people = get_people_from_url_ok(self.client, data_response["$pageview - val"]["2012-01-14"].person_url)

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
            person_response = get_people_from_url_ok(
                self.client, data_response["sign up - val"]["2012-01-13"].person_url
            )

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
            aggregate_person_response = get_people_from_url_ok(
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
            curr_people = get_people_from_url_ok(
                self.client, data_response["$pageview - current"]["2012-01-14"].person_url
            )
            prev_people = get_people_from_url_ok(
                self.client, data_response["$pageview - previous"]["2012-01-05"].person_url
            )

        assert sorted([p["id"] for p in curr_people]) == sorted(
            [str(created_people["p1"].uuid), str(created_people["p2"].uuid)]
        )
        assert sorted([p["id"] for p in prev_people]) == sorted(
            [str(created_people["p1"].uuid), str(created_people["p2"].uuid)]
        )


class ClickhouseTestTrendsGroups(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def _create_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:7", properties={"industry": "finance"})
        create_group(
            team_id=self.team.pk, group_type_index=1, group_key="company:10", properties={"industry": "finance"}
        )

    @snapshot_clickhouse_queries
    def test_aggregating_by_group(self):
        self._create_groups()

        events_by_person = {
            "person1": [
                {"event": "$pageview", "timestamp": datetime(2020, 1, 2, 12), "properties": {"$group_0": "org:5"}},
                {"event": "$pageview", "timestamp": datetime(2020, 1, 2, 12), "properties": {"$group_0": "org:6"}},
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:6", "$group_1": "company:10"},
                },
            ],
        }
        journeys_for(events_by_person, self.team)

        request = TrendsRequest(
            date_from="2020-01-01 00:00:00",
            date_to="2020-01-12 00:00:00",
            events=[
                {"id": "$pageview", "type": "events", "order": 0, "math": "unique_group", "math_group_type_index": 0,}
            ],
        )
        data_response = get_trends_time_series_ok(self.client, request, self.team)

        assert data_response["$pageview"]["2020-01-01"].value == 0
        assert data_response["$pageview"]["2020-01-02"].value == 2

        curr_people = get_people_from_url_ok(self.client, data_response["$pageview"]["2020-01-02"].person_url)

        assert sorted([p["group_key"] for p in curr_people]) == sorted(["org:5", "org:6"])
