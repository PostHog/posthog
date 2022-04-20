from datetime import datetime, timedelta
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.cohort_query import CohortQuery
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.client import sync_execute
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.test.base import BaseTest


def _create_event(**kwargs) -> None:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)


class TestCohortQuery(ClickhouseTestMixin, BaseTest):
    def test_basic_query(self):

        action1 = Action.objects.create(team=self.team, name="action1")
        step1 = ActionStep.objects.create(
            event="$autocapture", action=action1, url="https://posthog.com/feedback/123", url_matching=ActionStep.EXACT,
        )

        # satiesfies all conditions
        p1 = Person.objects.create(
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
        p2 = Person.objects.create(
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
                                    "event_type": "event",
                                    "time_value": 1,
                                    "time_interval": "day",
                                    "type": "performed_event",
                                },
                                {
                                    "key": "$pageview",
                                    "event_type": "event",
                                    "time_value": 2,
                                    "time_interval": "week",
                                    "type": "performed_event",
                                },
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": action1.pk,
                                    "event_type": "action",
                                    "time_value": 2,
                                    "time_interval": "week",
                                    "type": "performed_event_first_time",
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

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_performed_event(self):
        p1 = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=2),
        )

        p2 = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=9),
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "event",
                            "time_value": 1,
                            "time_interval": "week",
                            "type": "performed_event",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_performed_event_multiple(self):
        p1 = Person.objects.create(
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

        p2 = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=9),
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "event",
                            "operator": "gte",
                            "operator_value": 1,
                            "time_value": 1,
                            "time_interval": "week",
                            "type": "performed_event_multiple",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_stopped_performing_event(self):
        p1 = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(days=10),
        )

        p2 = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "test", "email": "test@posthog.com"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            properties={},
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(days=3),
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "event",
                            "time_value": 1,
                            "time_interval": "week",
                            "seq_time_value": 1,
                            "seq_time_interval": "week",
                            "type": "stopped_performing_event",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_restarted_performing_event(self):
        pass

    def test_performed_event_first_time(self):
        pass

    def test_performed_event_sequence(self):
        pass

    def test_performed_event_regularly(self):
        p1 = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test", "email": "test@posthog.com"}
        )
        for i in range(10):
            _create_event(
                team=self.team,
                event="$pageview",
                properties={},
                distinct_id="p1",
                timestamp=datetime.now() - timedelta(days=3 * i, hours=1),
            )

        filter = Filter(
            data={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "event",
                            "operator": "gte",
                            "operator_value": 1,
                            "time_interval": "day",
                            "time_value": 3,
                            "total_periods": 11,
                            "min_periods": 10,
                            "type": "performed_event_regularly",
                        }
                    ],
                },
            }
        )

        q, params = CohortQuery(filter=filter, team=self.team).get_query()
        res = sync_execute(q, params)

        self.assertEqual([p1.uuid], [r[0] for r in res])

    def test_person_props(self):
        pass
