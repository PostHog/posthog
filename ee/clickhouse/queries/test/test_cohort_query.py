from datetime import datetime, timedelta

from ee.clickhouse.queries.enterprise_cohort_query import check_negation_clause
from posthog.client import sync_execute
from posthog.constants import PropertyOperatorType
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.filters.filter import Filter
from posthog.models.property import Property, PropertyGroup
from posthog.queries.cohort_query import CohortQuery
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
    test_with_materialized_columns,
)


def _make_event_sequence(team, distinct_id, interval_days, period_event_counts, event="$pageview"):
    for period_index, event_count in enumerate(period_event_counts):
        for i in range(event_count):
            _create_event(
                team=team,
                event=event,
                properties={},
                distinct_id=distinct_id,
                timestamp=datetime.now() - timedelta(days=interval_days * period_index, hours=1, minutes=i),
            )


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    is_static = kwargs.pop("is_static", False)
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, is_static=is_static)
    return cohort


class TestCohortQuery(ClickhouseTestMixin, BaseTest):
    @snapshot_clickhouse_queries
    def test_basic_query(self):

        action1 = Action.objects.create(team=self.team, name="action1")
        step1 = ActionStep.objects.create(
            event="$autocapture", action=action1, url="https://posthog.com/feedback/123", url_matching=ActionStep.EXACT,
        )

        # satiesfies all conditions
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=1),
        )

        # doesn't satisfy action
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(weeks=3),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=1),
        )

        # doesn't satisfy property condition
        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test", "email": "testXX@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=2),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=1),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$pageview",
                                    "event_type": "events",
                                    "time_value": 1,
                                    "time_interval": "day",
                                    "value": "performed_event",
                                    "type": "behavioral",
                                },
                                {
                                    "key": "$pageview",
                                    "event_type": "events",
                                    "time_value": 2,
                                    "time_interval": "week",
                                    "value": "performed_event",
                                    "type": "behavioral",
                                },
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": action1.pk,
                                    "event_type": "actions",
                                    "time_value": 2,
                                    "time_interval": "week",
                                    "value": "performed_event_first_time",
                                    "type": "behavioral",
                                },
                                {"key": "email", "value": "test@posthog.com", "type": "person"},
                            ],
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        # Since all props should be pushed down here, there should be no full outer join!
        self.assertTrue("FULL OUTER JOIN" not in q)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_performed_event(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=9),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_performed_event_multiple(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )

        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=4),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=9),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 1,
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event_multiple",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_performed_event_lte_1_times(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(hours=9),
        )

        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test3", "email": "test3@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(hours=9),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(hours=8),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "lte",
                            "operator_value": 1,
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event_multiple",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual(set([p2.uuid]), set([r[0] for r in res]))

    def test_performed_event_zero_times_(self):
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "eq",
                            "operator_value": 0,
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event_multiple",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )
        with self.assertRaises(ValueError):
            CohortQuery(filter=filter, team=self.team).get_query()

    def test_stopped_performing_event(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=10),
        )

        _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=3),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "seq_time_value": 1,
                            "seq_time_interval": "week",
                            "value": "stopped_performing_event",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_stopped_performing_event_raises_if_seq_date_later_than_date(self):
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "day",
                            "seq_time_value": 2,
                            "seq_time_interval": "day",
                            "value": "stopped_performing_event",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        with self.assertRaises(ValueError):
            CohortQuery(filter=filter, team=self.team).get_query()

    def test_restarted_performing_event(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test2", "email": "test2@posthog.com"}
        )
        _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test3", "email": "test3@posthog.com"}
        )

        # P1 events (proper restarting sequence)
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=20),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=1),
        )

        # P2 events (an event occurs in the middle of the sequence, so the event never "stops")
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=20),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=5),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=1),
        )

        # P3 events (the event just started, so it isn't considered a restart)
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=1),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "seq_time_value": 2,
                            "seq_time_interval": "day",
                            "value": "restarted_performing_event",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_restarted_performing_event_raises_if_seq_date_later_than_date(self):
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "day",
                            "seq_time_value": 2,
                            "seq_time_interval": "day",
                            "value": "restarted_performing_event",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        with self.assertRaises(ValueError):
            CohortQuery(filter=filter, team=self.team).get_query()

    def test_performed_event_first_time(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test2", "email": "test2@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=20),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=4),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=4),
        )
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p2.uuid], [r[0] for r in res])

    def test_performed_event_regularly(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _make_event_sequence(self.team, "p1", 3, [1, 1, 1])
        flush_persons_and_events()
        # Filter for:
        # Regularly completed [$pageview] [at least] [1] times per
        # [3][day] period for at least [3] of the last [3] periods
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 1,
                            "time_interval": "day",
                            "time_value": 3,
                            "total_periods": 3,
                            "min_periods": 3,
                            "value": "performed_event_regularly",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_performed_event_regularly_with_variable_event_counts_in_each_period(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test2", "email": "test2@posthog.com"}
        )
        # p1 gets variable number of events in each period
        _make_event_sequence(self.team, "p1", 3, [0, 1, 2])
        # p2 gets 10 events in each period
        _make_event_sequence(self.team, "p2", 3, [1, 2, 2])

        # Filter for:
        # Regularly completed [$pageview] [at least] [2] times per
        # [3][day] period for at least [2] of the last [3] periods
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 2,
                            "time_interval": "day",
                            "time_value": 3,
                            "total_periods": 3,
                            "min_periods": 2,
                            "value": "performed_event_regularly",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)
        self.assertEqual([p2.uuid], [r[0] for r in res])
        flush_persons_and_events()

        # Filter for:
        # Regularly completed [$pageview] [at least] [1] times per
        # [3][day] period for at least [2] of the last [3] periods
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 1,
                            "time_interval": "day",
                            "time_value": 3,
                            "total_periods": 3,
                            "min_periods": 2,
                            "value": "performed_event_regularly",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)
        self.assertEqual(set([p1.uuid, p2.uuid]), set([r[0] for r in res]))

    @snapshot_clickhouse_queries
    def test_person_props_only(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test1@posthog.com"}
        )
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test2@posthog.com"}
        )
        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test3", "email": "test3@posthog.com"}
        )
        # doesn't match
        p4 = _create_person(
            team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "test3", "email": "test4@posthog.com"}
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "email", "value": "test1@posthog.com", "type": "person"},
                                {"key": "email", "value": "test2@posthog.com", "type": "person"},
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {"key": "name", "value": "test3", "type": "person"},
                                {"key": "email", "value": "test3@posthog.com", "type": "person"},
                            ],
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        # Since all props should be pushed down here, there should be no full outer join!
        self.assertTrue("FULL OUTER JOIN" not in q)

        self.assertCountEqual([p1.uuid, p2.uuid, p3.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_person_properties_with_pushdowns(self):

        action1 = Action.objects.create(team=self.team, name="action1")
        ActionStep.objects.create(
            event="$autocapture", action=action1, url="https://posthog.com/feedback/123", url_matching=ActionStep.EXACT,
        )

        # satiesfies all conditions
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=1),
        )

        # doesn't satisfy action
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(weeks=3),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=1),
        )

        # satisfies special condition (not pushed down person property in OR group)
        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "special", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=2),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$pageview",
                                    "event_type": "events",
                                    "time_value": 1,
                                    "time_interval": "day",
                                    "value": "performed_event",
                                    "type": "behavioral",
                                },
                                {
                                    "key": "$pageview",
                                    "event_type": "events",
                                    "time_value": 2,
                                    "time_interval": "week",
                                    "value": "performed_event",
                                    "type": "behavioral",
                                },
                                {"key": "name", "value": "special", "type": "person"},  # this is NOT pushed down
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": action1.pk,
                                    "event_type": "actions",
                                    "time_value": 2,
                                    "time_interval": "week",
                                    "value": "performed_event_first_time",
                                    "type": "behavioral",
                                },
                                {"key": "email", "value": "test@posthog.com", "type": "person"},  # this is pushed down
                            ],
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertCountEqual([p1.uuid, p3.uuid], [r[0] for r in res])

    @test_with_materialized_columns(person_properties=["$sample_field"])
    @snapshot_clickhouse_queries
    def test_person(self):

        # satiesfies all conditions
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "$sample_field": "test@posthog.com"}
        )
        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                        {"key": "$sample_field", "value": "test@posthog.com", "type": "person"},
                    ],
                },
            }
        )
        flush_persons_and_events()

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_earliest_date_clause(self):
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_multiple",
                            "operator_value": 1,
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 4,
                            "time_interval": "week",
                            "seq_time_value": 1,
                            "seq_time_interval": "week",
                            "value": "stopped_performing_event",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 2,
                            "time_interval": "week",
                            "time_value": 3,
                            "total_periods": 3,
                            "min_periods": 2,
                            "value": "performed_event_regularly",
                            "type": "behavioral",
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        sync_execute(q, params)

        self.assertTrue("timestamp >= now() - INTERVAL 9 week" in (q % params))

    def test_earliest_date_clause_removed_for_started_at_query(self):
        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 2,
                            "time_interval": "week",
                            "time_value": 3,
                            "total_periods": 3,
                            "min_periods": 2,
                            "value": "performed_event_regularly",
                            "type": "behavioral",
                        },
                    ],
                },
            }
        )
        query_class = CohortQuery(filter=filter, team=self.team)
        q, params = query_class.get_query()
        self.assertFalse(query_class._restrict_event_query_by_time)
        sync_execute(q, params)

    def test_negation(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=10),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                            "negation": True,
                        },
                    ],
                },
            }
        )

        self.assertRaises(ValueError, lambda: CohortQuery(filter=filter, team=self.team))

    def test_negation_with_simplify_filters(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=10),
        )

        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=10),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "type": "behavioral",
                            "value": "performed_event",
                            "negation": True,
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                        },
                        {
                            "key": "$feature_flag_called",
                            "type": "behavioral",
                            "value": "performed_event",
                            "negation": False,
                            "event_type": "events",
                            "time_value": "30",
                            "time_interval": "day",
                        },
                    ],
                }
            },
            team=self.team,
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)
        self.assertCountEqual([p3.uuid], [r[0] for r in res])

    def test_negation_dynamic_time_bound_with_performed_event(self):
        # invalid dude because $pageview happened too early
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )

        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=4),
        )

        # invalid dude because no new_view event
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=4),
        )

        # valid dude because $pageview happened a long time ago
        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=35),
        )

        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=4),
        )

        # valid dude because $pageview did not happen
        p4 = _create_person(
            team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p4",
            timestamp=datetime.now() - timedelta(days=4),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$new_view",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                            "negation": True,
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertCountEqual([p3.uuid, p4.uuid], [r[0] for r in res])

    def test_negation_dynamic_time_bound_with_performed_event_sequence(self):
        # invalid dude because $pageview sequence happened too early
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        # pageview sequence that happens today, and 2 days ago
        _make_event_sequence(self.team, "p1", 2, [1, 1])
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=4),
        )

        # invalid dude because no new_view event
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _make_event_sequence(self.team, "p2", 2, [1, 1])

        # valid dude because $pageview sequence happened a long time ago
        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=35),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=37),
        )
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=4),
        )

        # valid dude because $pageview sequence did not happen
        p4 = _create_person(
            team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p4",
            timestamp=datetime.now() - timedelta(days=4),
        )

        # valid dude because $pageview sequence did not complete, even if one pageview happened
        p5 = _create_person(
            team_id=self.team.pk, distinct_ids=["p5"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p5",
            timestamp=datetime.now() - timedelta(days=5),
        )
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p5",
            timestamp=datetime.now() - timedelta(days=4),
        )

        # valid dude because $pageview sequence delay was long enough, even if it happened too early
        p6 = _create_person(
            team_id=self.team.pk, distinct_ids=["p6"], properties={"name": "test", "email": "test@posthog.com"}
        )
        # pageview sequence that happens today, and 4 days ago
        _make_event_sequence(self.team, "p6", 4, [1, 1])
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p6",
            timestamp=datetime.now() - timedelta(days=4),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$new_view",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 8,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                            "negation": True,
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)
        self.assertCountEqual([p3.uuid, p4.uuid, p5.uuid, p6.uuid], [r[0] for r in res])

    def test_cohort_filter(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "name": "test"})
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )
        flush_persons_and_events()

        filter = Filter(
            data={"properties": {"type": "AND", "values": [{"key": "id", "value": cohort.pk, "type": "cohort"}],},},
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_faulty_type(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {"properties": [{"key": "email", "type": "event", "value": ["fake@test.com"], "operator": "exact"}]}
            ],
        )

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "email", "value": ["fake@test.com"], "operator": "exact", "type": "person"}],
                    }
                ],
            },
        )

    def test_missing_type(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "email", "value": ["fake@test.com"], "operator": "exact"}]}],
        )

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "email", "value": ["fake@test.com"], "operator": "exact", "type": "person"}],
                    }
                ],
            },
        )

    def test_old_old_style_properties(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {"properties": [{"key": "email", "value": ["fake@test.com"], "operator": "exact"}]},
                {"properties": {"abra": "cadabra", "name": "alakazam"}},
            ],
        )

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "email", "value": ["fake@test.com"], "operator": "exact", "type": "person"}],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {"key": "abra", "value": "cadabra", "type": "person"},
                            {"key": "name", "value": "alakazam", "type": "person"},
                        ],
                    },
                ],
            },
        )

    def test_precalculated_cohort_filter(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "name": "test"})
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [{"key": "id", "value": cohort.pk, "type": "precalculated-cohort"}],
                },
            }
        )

        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            q, params = CohortQuery(filter=filter, team=self.team).get_query()
            # Precalculated cohorts should not be used as is
            # since we want cohort calculation with cohort properties to not be out of sync
            self.assertTrue("cohortpeople" not in q)
            res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_precalculated_cohort_filter_with_extra_filters(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test"})
        p2 = _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test2"})
        p3 = _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test3"})

        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"key": "id", "value": cohort.pk, "type": "precalculated-cohort"},
                        {"key": "name", "value": "test2", "type": "person",},
                    ],
                },
            }
        )

        # makes sure cohort is precalculated
        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            q, params = CohortQuery(filter=filter, team=self.team).get_query()
            self.assertTrue("cohortpeople" not in q)
            res = sync_execute(q, params)

        self.assertCountEqual([p1.uuid, p2.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_cohort_filter_with_extra(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "name": "test"})
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=2),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort.pk, "type": "cohort"},
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                    ],
                },
            },
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p2.uuid], [r[0] for r in res])

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"key": "id", "value": cohort.pk, "type": "cohort"},
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                    ],
                },
            },
            team=self.team,
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertCountEqual([p1.uuid, p2.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_cohort_filter_with_another_cohort_with_event_sequence(self):
        # passes filters for cohortCeption, but not main cohort
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@gmail.com"}
        )
        _make_event_sequence(self.team, "p1", 2, [1, 1])

        # passes filters for cohortCeption and main cohort
        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _make_event_sequence(self.team, "p2", 2, [1, 1])
        _make_event_sequence(self.team, "p2", 6, [1, 1], event="$new_view")

        # passes filters for neither cohortCeption nor main cohort
        p3 = _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"email": "test@posthog.com"})
        _make_event_sequence(self.team, "p3", 2, [1, 1])

        # passes filters for mainCohort but not cohortCeption
        p4 = _create_person(
            team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _make_event_sequence(self.team, "p4", 6, [1, 1])
        _make_event_sequence(self.team, "p4", 6, [1, 1], event="$new_view")
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            name="cohortCeption",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "name", "value": "test", "type": "person"},
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 8,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                    ],
                },
            },
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort.pk, "type": "cohort"},
                        {
                            "key": "$new_view",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 8,
                            "seq_time_interval": "day",
                            "seq_time_value": 8,
                            "seq_event": "$new_view",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                    ],
                },
            },
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p2.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_static_cohort_filter(self):

        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "name": "test"})
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[], is_static=True,)
        flush_persons_and_events()
        cohort.insert_users_by_list(["p1"])

        filter = Filter(
            data={
                "properties": {"type": "OR", "values": [{"key": "id", "value": cohort.pk, "type": "static-cohort"}],},
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_static_cohort_filter_with_extra(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "name": "test"})
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[], is_static=True,)

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=2),
        )
        flush_persons_and_events()
        cohort.insert_users_by_list(["p1", "p2"])

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort.pk, "type": "cohort"},
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                    ],
                },
            },
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p2.uuid], [r[0] for r in res])

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"key": "id", "value": cohort.pk, "type": "cohort"},
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                    ],
                },
            },
            team=self.team,
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertCountEqual([p1.uuid, p2.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_performed_event_sequence(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _make_event_sequence(self.team, "p1", 2, [1, 1])

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=2),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_performed_event_sequence_with_restarted(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _make_event_sequence(self.team, "p1", 2, [1, 1])

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=18),
        )
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=5),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                        {
                            "key": "$new_view",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "seq_time_value": 1,
                            "seq_time_interval": "week",
                            "value": "restarted_performing_event",
                            "type": "behavioral",
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual(sorted([p1.uuid, p2.uuid]), sorted([r[0] for r in res]))

    def test_performed_event_sequence_with_extra_conditions(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _make_event_sequence(self.team, "p1", 2, [1, 1])

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=4),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=2),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 1,
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event_multiple",
                            "type": "behavioral",
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_performed_event_sequence_with_person_properties(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _make_event_sequence(self.team, "p1", 2, [1, 1])

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=4),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=2),
        )

        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test22", "email": "test22@posthog.com"}
        )

        _make_event_sequence(self.team, "p3", 2, [1, 1])

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=2),
        )

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=4),
        )

        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 1,
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event_multiple",
                            "type": "behavioral",
                        },
                        {"key": "email", "value": "test@posthog.com", "type": "person"},  # pushed down
                    ],
                },
            },
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_multiple_performed_event_sequence(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _make_event_sequence(self.team, "p1", 2, [1, 1])

        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=10),
        )

        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=9),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=10),
        )

        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=9),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "week",
                            "time_value": 2,
                            "seq_time_interval": "day",
                            "seq_time_value": 2,
                            "seq_event": "$new_view",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    @snapshot_clickhouse_queries
    def test_performed_event_sequence_and_clause_with_additional_event(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=6),
        )

        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=5),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=3),
        )
        flush_persons_and_events()

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                        {
                            "key": "$new_view",
                            "event_type": "events",
                            "operator": "gte",
                            "operator_value": 1,
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event_multiple",
                            "type": "behavioral",
                        },
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual(set([p1.uuid, p2.uuid]), set([r[0] for r in res]))

    @snapshot_clickhouse_queries
    def test_unwrapping_static_cohort_filter_hidden_in_layers_of_cohorts(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "name": "test"})
        cohort_static = _create_cohort(team=self.team, name="cohort static", groups=[], is_static=True,)

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=2),
        )

        p3 = _create_person(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test"})
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=1),
        )

        p4 = _create_person(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "test"})
        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p4",
            timestamp=datetime.now() - timedelta(days=1),
        )
        p5 = _create_person(team_id=self.team.pk, distinct_ids=["p5"], properties={"name": "test"})
        flush_persons_and_events()
        cohort_static.insert_users_by_list(["p4", "p5"])

        other_cohort = Cohort.objects.create(
            team=self.team,
            name="cohort other",
            is_static=False,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$new_view",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "value": "performed_event",
                            "type": "behavioral",
                            # p3, p4 fits in here
                        },
                        {
                            "key": "id",
                            "value": cohort_static.pk,
                            "type": "cohort",
                            "negation": True,
                            # p4, p5 fits in here
                        },
                    ],
                }
            },
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"key": "id", "value": other_cohort.pk, "type": "cohort"},  # p3 fits in here
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 1,
                            "time_interval": "week",
                            "value": "performed_event",
                            "type": "behavioral",
                            # p2 fits in here
                        },
                    ],
                },
            },
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertCountEqual([p2.uuid, p3.uuid], [r[0] for r in res])

    def test_unwrap_with_negated_cohort(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test2", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=6),
        )
        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=6),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=6),
        )

        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test2", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=6),
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            name="cohort 1",
            is_static=False,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$new_view",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                    ],
                }
            },
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            name="cohort 2",
            is_static=False,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$some_event",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                        {"key": "name", "value": "test2", "type": "person", "negation": True},
                        {"key": "id", "value": cohort1.pk, "type": "cohort", "negation": True,},
                    ],
                }
            },
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [{"key": "id", "value": cohort2.pk, "type": "cohort"},],  # p3 fits in here
                },
            },
            team=self.team,
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertCountEqual([p2.uuid], [r[0] for r in res])

    def test_unwrap_multiple_levels(self):
        p1 = _create_person(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test2", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$new_view",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=6),
        )
        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=6),
        )

        p2 = _create_person(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=6),
        )

        p3 = _create_person(
            team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "test2", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$some_event",
            properties={},
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=6),
        )

        p4 = _create_person(
            team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "test3", "email": "test@posthog.com"}
        )

        _create_event(
            team=self.team,
            event="$target_event",
            properties={},
            distinct_id="p4",
            timestamp=datetime.now() - timedelta(days=6),
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            name="cohort 1",
            is_static=False,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$new_view",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                    ],
                }
            },
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            name="cohort 2",
            is_static=False,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$some_event",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 7,
                            "value": "performed_event",
                            "type": "behavioral",
                        },
                        {"key": "name", "value": "test2", "type": "person", "negation": True},
                        {"key": "id", "value": cohort1.pk, "type": "cohort", "negation": True,},
                    ],
                }
            },
        )

        cohort3 = Cohort.objects.create(
            team=self.team,
            name="cohort 3",
            is_static=False,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "name", "value": "test3", "type": "person"},
                        {"key": "id", "value": cohort2.pk, "type": "cohort", "negation": True,},
                    ],
                }
            },
        )

        filter = Filter(
            data={"properties": {"type": "OR", "values": [{"key": "id", "value": cohort3.pk, "type": "cohort"},],},},
            team=self.team,
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertCountEqual([p4.uuid], [r[0] for r in res])


class TestCohortNegationValidation(BaseTest):
    def test_basic_valid_negation_tree(self):

        property_group = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[
                Property(key="name", value="test", type="person",),
                Property(key="email", value="xxx", type="person", negation=True,),
            ],
        )

        has_pending_neg, has_reg = check_negation_clause(property_group)
        self.assertEqual(has_pending_neg, False)
        self.assertEqual(has_reg, True)

    def test_valid_negation_tree_with_extra_layers(self):

        property_group = PropertyGroup(
            type=PropertyOperatorType.OR,
            values=[
                PropertyGroup(
                    type=PropertyOperatorType.AND, values=[Property(key="name", value="test", type="person",),],
                ),
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        PropertyGroup(
                            type=PropertyOperatorType.OR,
                            values=[Property(key="email", value="xxx", type="person", negation=True,),],
                        ),
                        PropertyGroup(
                            type=PropertyOperatorType.OR, values=[Property(key="email", value="xxx", type="person",),]
                        ),
                    ],
                ),
            ],
        )

        has_pending_neg, has_reg = check_negation_clause(property_group)
        self.assertEqual(has_pending_neg, False)
        self.assertEqual(has_reg, True)

    def test_invalid_negation_tree_with_extra_layers(self):

        property_group = PropertyGroup(
            type=PropertyOperatorType.OR,
            values=[
                PropertyGroup(
                    type=PropertyOperatorType.AND, values=[Property(key="name", value="test", type="person",),],
                ),
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        PropertyGroup(
                            type=PropertyOperatorType.OR,
                            values=[Property(key="email", value="xxx", type="person", negation=True,),],
                        ),
                        PropertyGroup(
                            type=PropertyOperatorType.OR,
                            values=[Property(key="email", value="xxx", type="person", negation=True,),],
                        ),
                    ],
                ),
            ],
        )

        has_pending_neg, has_reg = check_negation_clause(property_group)
        self.assertEqual(has_pending_neg, True)
        self.assertEqual(has_reg, True)

    def test_valid_negation_tree_with_extra_layers_recombining_at_top(self):

        property_group = PropertyGroup(
            type=PropertyOperatorType.AND,  # top level AND protects the 2 negations from being invalid
            values=[
                PropertyGroup(
                    type=PropertyOperatorType.OR, values=[Property(key="name", value="test", type="person",),],
                ),
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        PropertyGroup(
                            type=PropertyOperatorType.OR,
                            values=[Property(key="email", value="xxx", type="person", negation=True,),],
                        ),
                        PropertyGroup(
                            type=PropertyOperatorType.OR,
                            values=[Property(key="email", value="xxx", type="person", negation=True,),],
                        ),
                    ],
                ),
            ],
        )

        has_pending_neg, has_reg = check_negation_clause(property_group)
        self.assertEqual(has_pending_neg, False)
        self.assertEqual(has_reg, True)

    def test_invalid_negation_tree_no_positive_filter(self):

        property_group = PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[
                PropertyGroup(
                    type=PropertyOperatorType.OR,
                    values=[Property(key="name", value="test", type="person", negation=True,),],
                ),
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        PropertyGroup(
                            type=PropertyOperatorType.OR,
                            values=[Property(key="email", value="xxx", type="person", negation=True,),],
                        ),
                        PropertyGroup(
                            type=PropertyOperatorType.OR,
                            values=[Property(key="email", value="xxx", type="person", negation=True,),],
                        ),
                    ],
                ),
            ],
        )

        has_pending_neg, has_reg = check_negation_clause(property_group)
        self.assertEqual(has_pending_neg, True)
        self.assertEqual(has_reg, False)

    def test_empty_property_group(self):

        property_group = PropertyGroup(
            type=PropertyOperatorType.AND, values=[],  # type: ignore
        )

        has_pending_neg, has_reg = check_negation_clause(property_group)
        self.assertEqual(has_pending_neg, False)
        self.assertEqual(has_reg, False)

    def test_basic_invalid_negation_tree(self):

        property_group = PropertyGroup(
            type=PropertyOperatorType.AND, values=[Property(key="email", value="xxx", type="person", negation=True,),],
        )

        has_pending_neg, has_reg = check_negation_clause(property_group)
        self.assertEqual(has_pending_neg, True)
        self.assertEqual(has_reg, False)

    def test_basic_valid_negation_tree_with_no_negations(self):

        property_group = PropertyGroup(
            type=PropertyOperatorType.AND, values=[Property(key="name", value="test", type="person",),],
        )

        has_pending_neg, has_reg = check_negation_clause(property_group)
        self.assertEqual(has_pending_neg, False)
        self.assertEqual(has_reg, True)
