from datetime import datetime, timedelta

from django.utils.timezone import now
from freezegun.api import freeze_time

from ee.clickhouse.models.group import create_group
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.constants import FILTER_TEST_ACCOUNTS, TRENDS_LIFECYCLE
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.filter import Filter
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person
from posthog.queries.test.test_lifecycle import lifecycle_test_factory
from posthog.test.base import _create_event, _create_person


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


class TestClickhouseLifecycle(ClickhouseTestMixin, lifecycle_test_factory(ClickhouseTrends, _create_event, _create_person, _create_action)):  # type: ignore
    @snapshot_clickhouse_queries
    def test_test_account_filters_with_groups(self):
        self.team.test_account_filters = [
            {"key": "key", "type": "group", "value": "value", "group_type_index": 0},
        ]
        self.team.save()

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        create_group(self.team.pk, group_type_index=0, group_key="in", properties={"key": "value"})
        create_group(self.team.pk, group_type_index=0, group_key="out", properties={"key": "othervalue"})

        with freeze_time("2020-01-11T12:00:00Z"):
            Person.objects.create(distinct_ids=["person1"], team_id=self.team.pk)

        with freeze_time("2020-01-09T12:00:00Z"):
            Person.objects.create(distinct_ids=["person2"], team_id=self.team.pk)

        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "timestamp": datetime(2020, 1, 11, 12), "properties": {"$group_0": "out"},},
                ],
                "person2": [
                    {"event": "$pageview", "timestamp": datetime(2020, 1, 9, 12), "properties": {"$group_0": "in"},},
                    {"event": "$pageview", "timestamp": datetime(2020, 1, 12, 12), "properties": {"$group_0": "in"},},
                    {"event": "$pageview", "timestamp": datetime(2020, 1, 15, 12), "properties": {"$group_0": "in"},},
                ],
            },
            self.team,
        )

        result = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                    FILTER_TEST_ACCOUNTS: True,
                },
                team=self.team,
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, -1, 0, 0, -1, 0, 0, 0]},
                {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [1, 0, 0, 1, 0, 0, 0, 0]},
                {"status": "returning", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
            ],
        )

    @snapshot_clickhouse_queries
    def test_lifecycle_edge_cases(self):
        # This test tests behavior when created_at is different from first matching event and dormant/resurrecting/returning logic
        with freeze_time("2020-01-11T12:00:00Z"):
            Person.objects.create(distinct_ids=["person1"], team_id=self.team.pk)

        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "timestamp": datetime(2020, 1, 12, 12),},
                    {"event": "$pageview", "timestamp": datetime(2020, 1, 13, 12),},
                    {"event": "$pageview", "timestamp": datetime(2020, 1, 15, 12),},
                    {"event": "$pageview", "timestamp": datetime(2020, 1, 16, 12),},
                ],
            },
            self.team,
        )

        result = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "2020-01-11T00:00:00Z",
                    "date_to": "2020-01-18T00:00:00Z",
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "shown_as": TRENDS_LIFECYCLE,
                },
                team=self.team,
            ),
            self.team,
        )

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0, 0, 0, -1, 0, 0, -1, 0]},
                {"status": "new", "data": [0, 0, 0, 0, 0, 0, 0, 0]},
                {"status": "resurrecting", "data": [0, 1, 0, 0, 1, 0, 0, 0]},
                {"status": "returning", "data": [0, 0, 1, 0, 0, 1, 0, 0]},
            ],
        )

    @snapshot_clickhouse_queries
    def test_interval_dates_days(self):
        with freeze_time("2021-05-05T12:00:00Z"):
            self._setup_returning_lifecycle_data(20)

            result = self._run_lifecycle({"date_from": "-7d", "interval": "day"})

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0] * 8},
                {"status": "new", "data": [0] * 8},
                {"status": "resurrecting", "data": [0] * 8},
                {"status": "returning", "data": [1] * 8},
            ],
        )
        self.assertEqual(
            result[0]["days"],
            [
                "2021-04-28",
                "2021-04-29",
                "2021-04-30",
                "2021-05-01",
                "2021-05-02",
                "2021-05-03",
                "2021-05-04",
                "2021-05-05",
            ],
        )

    @snapshot_clickhouse_queries
    def test_interval_dates_weeks(self):
        with freeze_time("2021-05-06T12:00:00Z"):
            self._setup_returning_lifecycle_data(50)

            result = self._run_lifecycle({"date_from": "-30d", "interval": "week"})

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0] * 5},
                {"status": "new", "data": [0] * 5},
                {"status": "resurrecting", "data": [0] * 5},
                {"status": "returning", "data": [1] * 5},
            ],
        )
        self.assertEqual(
            result[0]["days"], ["2021-04-05", "2021-04-12", "2021-04-19", "2021-04-26", "2021-05-03",],
        )

    @snapshot_clickhouse_queries
    def test_interval_dates_months(self):
        with freeze_time("2021-05-05T12:00:00Z"):
            self._setup_returning_lifecycle_data(120)

            result = self._run_lifecycle({"date_from": "-90d", "interval": "month"})

        self.assertLifecycleResults(
            result,
            [
                {"status": "dormant", "data": [0] * 4},
                {"status": "new", "data": [0] * 4},
                {"status": "resurrecting", "data": [0] * 4},
                {"status": "returning", "data": [1] * 4},
            ],
        )
        self.assertEqual(
            result[0]["days"], ["2021-02-01", "2021-03-01", "2021-04-01", "2021-05-01",],
        )

    def _setup_returning_lifecycle_data(self, days):
        with freeze_time("2019-01-01T12:00:00Z"):
            Person.objects.create(distinct_ids=["person1"], team_id=self.team.pk)

        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "timestamp": (now() - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S.%f")}
                    for n in range(days)
                ],
            },
            self.team,
            create_people=False,
        )

    def _run_lifecycle(self, data):
        filter = Filter(
            data={"events": [{"id": "$pageview", "type": "events", "order": 0}], "shown_as": TRENDS_LIFECYCLE, **data,},
            team=self.team,
        )
        return ClickhouseTrends().run(filter, self.team,)
