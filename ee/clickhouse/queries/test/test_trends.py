from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.models.action import populate_action_event_table
from ee.clickhouse.models.cohort import populate_cohort_person_table
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.queries.test.test_trends import trend_test_factory


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    populate_action_event_table(action)
    return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups)
    populate_cohort_person_table(cohort)
    return cohort


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseTrends(ClickhouseTestMixin, trend_test_factory(ClickhouseTrends, _create_event, Person.objects.create, _create_action, _create_cohort)):  # type: ignore
    def test_breakdown_filtering(self):
        self._create_events()
        # test breakdown filtering
        with freeze_time("2020-01-04T13:01:01Z"):
            response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "$some_property",
                        "events": [
                            {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                            {"id": "no events"},
                        ],
                    }
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], 'sign up - "value"')
        self.assertEqual(response[1]["label"], 'sign up - "other_value"')
        self.assertEqual(response[2]["label"], 'no events - "value"')
        self.assertEqual(response[3]["label"], 'no events - "other_value"')

        self.assertEqual(sum(response[0]["data"]), 2)
        self.assertEqual(response[0]["breakdown_value"], '"value"')

        self.assertEqual(sum(response[1]["data"]), 1)
        self.assertEqual(response[1]["breakdown_value"], '"other_value"')
