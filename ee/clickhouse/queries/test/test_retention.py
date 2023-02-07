from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.instance_setting import override_instance_config
from posthog.models.person import Person
from posthog.queries.retention import Retention
from posthog.queries.test.test_retention import _create_events, _date, pluck
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    also_test_with_materialized_columns,
    snapshot_clickhouse_queries,
)


class TestClickhouseRetention(ClickhouseTestMixin, APIBaseTest):
    def _create_groups_and_events(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})

        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:1", properties={})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:2", properties={})

        Person.objects.create(team=self.team, distinct_ids=["person1", "alias1"])
        Person.objects.create(team=self.team, distinct_ids=["person2"])
        Person.objects.create(team=self.team, distinct_ids=["person3"])

        _create_events(
            self.team,
            [
                ("person1", _date(0), {"$group_0": "org:5", "$group_1": "company:1"}),
                ("person2", _date(0), {"$group_0": "org:6"}),
                ("person3", _date(0)),
                ("person1", _date(1), {"$group_0": "org:5"}),
                ("person2", _date(1), {"$group_0": "org:6"}),
                ("person1", _date(7), {"$group_0": "org:5"}),
                ("person2", _date(7), {"$group_0": "org:6"}),
                ("person1", _date(14), {"$group_0": "org:5"}),
                ("person1", _date(month=1, day=-6), {"$group_0": "org:5", "$group_1": "company:1"}),
                ("person2", _date(month=1, day=-6), {"$group_0": "org:6"}),
                ("person2", _date(month=1, day=1), {"$group_0": "org:6"}),
                ("person1", _date(month=1, day=1), {"$group_0": "org:5"}),
                ("person2", _date(month=1, day=15), {"$group_0": "org:6", "$group_1": "company:1"}),
            ],
        )

    # TODO: Delete this test when moved to person-on-events
    def test_groups_filtering(self):
        self._create_groups_and_events()

        result = Retention().run(
            RetentionFilter(
                data={
                    "date_to": _date(10, month=1, hour=0),
                    "period": "Week",
                    "total_intervals": 7,
                    "properties": [{"key": "industry", "value": "technology", "type": "group", "group_type_index": 0}],
                },
                team=self.team,
            ),
            self.team,
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            [[1, 1, 0, 1, 1, 0, 1], [1, 0, 1, 1, 0, 1], [0, 0, 0, 0, 0], [1, 1, 0, 1], [1, 0, 1], [0, 0], [1]],
        )

        result = Retention().run(
            RetentionFilter(
                data={
                    "date_to": _date(10, month=1, hour=0),
                    "period": "Week",
                    "total_intervals": 7,
                    "properties": [
                        {"key": "industry", "value": "", "type": "group", "group_type_index": 0, "operator": "is_set"}
                    ],
                },
                team=self.team,
            ),
            self.team,
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            [[2, 2, 1, 2, 2, 0, 1], [2, 1, 2, 2, 0, 1], [1, 1, 1, 0, 0], [2, 2, 0, 1], [2, 0, 1], [0, 0], [1]],
        )

    # TODO: Delete this test when moved to person-on-events
    def test_groups_aggregating(self):
        self._create_groups_and_events()

        filter = RetentionFilter(
            data={
                "date_to": _date(10, month=1, hour=0),
                "period": "Week",
                "total_intervals": 7,
                "aggregation_group_type_index": 0,
            },
            team=self.team,
        )

        result = Retention().run(filter, self.team)
        self.assertEqual(
            pluck(result, "values", "count"),
            [[2, 2, 1, 2, 2, 0, 1], [2, 1, 2, 2, 0, 1], [1, 1, 1, 0, 0], [2, 2, 0, 1], [2, 0, 1], [0, 0], [1]],
        )

        actor_result, _ = Retention().actors_in_period(filter.shallow_clone({"selected_interval": 0}), self.team)
        self.assertCountEqual([actor["person"]["id"] for actor in actor_result], ["org:5", "org:6"])

        filter = RetentionFilter(
            data={
                "date_to": _date(10, month=1, hour=0),
                "period": "Week",
                "total_intervals": 7,
                "aggregation_group_type_index": 1,
            },
            team=self.team,
        )

        result = Retention().run(filter, self.team)
        self.assertEqual(
            pluck(result, "values", "count"),
            [[1, 0, 0, 1, 0, 0, 1], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [1, 0, 0, 1], [0, 0, 0], [0, 0], [1]],
        )

    # TODO: Delete this test when moved to person-on-events
    def test_groups_in_period(self):
        self._create_groups_and_events()

        filter = RetentionFilter(
            data={
                "date_to": _date(10, month=1, hour=0),
                "period": "Week",
                "total_intervals": 7,
                "aggregation_group_type_index": 0,
            },
            team=self.team,
        )

        actor_result, _ = Retention().actors_in_period(filter.shallow_clone({"selected_interval": 0}), self.team)

        self.assertEqual(actor_result[0]["person"]["id"], "org:5")
        self.assertEqual(actor_result[0]["appearances"], [1, 1, 1, 1, 1, 0, 0])

        self.assertEqual(actor_result[1]["person"]["id"], "org:6")
        self.assertEqual(actor_result[1]["appearances"], [1, 1, 0, 1, 1, 0, 1])

    @also_test_with_materialized_columns(
        group_properties=[(0, "industry")], materialize_only_with_person_on_events=True
    )
    @snapshot_clickhouse_queries
    def test_groups_filtering_person_on_events(self):
        self._create_groups_and_events()

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            result = Retention().run(
                RetentionFilter(
                    data={
                        "date_to": _date(10, month=1, hour=0),
                        "period": "Week",
                        "total_intervals": 7,
                        "properties": [
                            {"key": "industry", "value": "technology", "type": "group", "group_type_index": 0}
                        ],
                    },
                    team=self.team,
                ),
                self.team,
            )

            self.assertEqual(
                pluck(result, "values", "count"),
                [[1, 1, 0, 1, 1, 0, 1], [1, 0, 1, 1, 0, 1], [0, 0, 0, 0, 0], [1, 1, 0, 1], [1, 0, 1], [0, 0], [1]],
            )

            result = Retention().run(
                RetentionFilter(
                    data={
                        "date_to": _date(10, month=1, hour=0),
                        "period": "Week",
                        "total_intervals": 7,
                        "properties": [
                            {
                                "key": "industry",
                                "value": "",
                                "type": "group",
                                "group_type_index": 0,
                                "operator": "is_set",
                            }
                        ],
                    },
                    team=self.team,
                ),
                self.team,
            )

            self.assertEqual(
                pluck(result, "values", "count"),
                [[2, 2, 1, 2, 2, 0, 1], [2, 1, 2, 2, 0, 1], [1, 1, 1, 0, 0], [2, 2, 0, 1], [2, 0, 1], [0, 0], [1]],
            )

    @also_test_with_materialized_columns(group_properties=[(0, "industry")])
    @snapshot_clickhouse_queries
    def test_groups_aggregating_person_on_events(self):
        self._create_groups_and_events()

        filter = RetentionFilter(
            data={
                "date_to": _date(10, month=1, hour=0),
                "period": "Week",
                "total_intervals": 7,
                "aggregation_group_type_index": 0,
            },
            team=self.team,
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):

            result = Retention().run(filter, self.team)
            self.assertEqual(
                pluck(result, "values", "count"),
                [[2, 2, 1, 2, 2, 0, 1], [2, 1, 2, 2, 0, 1], [1, 1, 1, 0, 0], [2, 2, 0, 1], [2, 0, 1], [0, 0], [1]],
            )

            actor_result, _ = Retention().actors_in_period(filter.shallow_clone({"selected_interval": 0}), self.team)

            self.assertCountEqual([actor["person"]["id"] for actor in actor_result], ["org:5", "org:6"])

            filter = RetentionFilter(
                data={
                    "date_to": _date(10, month=1, hour=0),
                    "period": "Week",
                    "total_intervals": 7,
                    "aggregation_group_type_index": 1,
                },
                team=self.team,
            )

            result = Retention().run(filter, self.team)
            self.assertEqual(
                pluck(result, "values", "count"),
                [[1, 0, 0, 1, 0, 0, 1], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [1, 0, 0, 1], [0, 0, 0], [0, 0], [1]],
            )

    @also_test_with_materialized_columns(group_properties=[(0, "industry")])
    @snapshot_clickhouse_queries
    def test_groups_in_period_person_on_events(self):
        from posthog.models.team import util

        util.can_enable_actor_on_events = True
        self._create_groups_and_events()

        filter = RetentionFilter(
            data={
                "date_to": _date(10, month=1, hour=0),
                "period": "Week",
                "total_intervals": 7,
                "aggregation_group_type_index": 0,
            },
            team=self.team,
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            actor_result, _ = Retention().actors_in_period(filter.shallow_clone({"selected_interval": 0}), self.team)

            self.assertTrue(actor_result[0]["person"]["id"] == "org:5")
            self.assertEqual(actor_result[0]["appearances"], [1, 1, 1, 1, 1, 0, 0])

            self.assertTrue(actor_result[1]["person"]["id"] == "org:6")
            self.assertEqual(actor_result[1]["appearances"], [1, 1, 0, 1, 1, 0, 1])
