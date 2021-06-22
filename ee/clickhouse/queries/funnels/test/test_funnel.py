from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel, ClickhouseFunnelNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.queries.test.test_funnel import funnel_test_factory
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnel(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnel, _create_event, _create_person)):  # type: ignore
    pass


class TestFunnelNew(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        self._create_sample_data()
        super().setUp()

    def _create_sample_data(self):
        # five people, three steps
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)
        _create_person(distinct_ids=["user_three"], team=self.team)
        _create_person(distinct_ids=["user_four"], team=self.team)
        _create_person(distinct_ids=["user_five"], team=self.team)
        _create_person(distinct_ids=["user_six"], team=self.team)
        _create_person(distinct_ids=["user_seven"], team=self.team)
        _create_person(distinct_ids=["user_eight"], team=self.team)

        _create_event(
            event="step one",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-02 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step two",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Chrome"},
        )
        _create_event(
            event="step three",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-05 00:00:00",
            properties={"$browser": "Chrome"},
        )

        _create_event(
            event="step one",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-02 00:00:00",
            properties={"$browser": "Safari"},
        )
        _create_event(
            event="step two",
            distinct_id="user_two",
            team=self.team,
            timestamp="2021-05-03 00:00:00",
            properties={"$browser": "Safari"},
        )

        _create_event(event="step one", distinct_id="user_three", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step three", distinct_id="user_three", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step two", distinct_id="user_three", team=self.team, timestamp="2021-05-04 00:00:00")

        _create_event(event="step one", distinct_id="user_three", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step three", distinct_id="user_three", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step two", distinct_id="user_three", team=self.team, timestamp="2021-05-04 00:00:00")

        _create_event(event="step one", distinct_id="user_four", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_four", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_four", team=self.team, timestamp="2021-05-07 00:00:00")

        _create_event(event="step one", distinct_id="user_six", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_six", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_six", team=self.team, timestamp="2021-05-03 01:00:00")
        _create_event(event="step four", distinct_id="user_six", team=self.team, timestamp="2021-05-03 02:00:00")
        _create_event(event="step five", distinct_id="user_six", team=self.team, timestamp="2021-05-04 00:00:00")
        _create_event(event="step six", distinct_id="user_six", team=self.team, timestamp="2021-05-04 04:00:00")

    def test_base_event_query(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "funnel_window_days": 4,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                    {"id": "step four", "order": 2},
                    {"id": "step five", "order": 2},
                    {"id": "step six", "order": 2},
                ],
            }
        )
        query_builder = ClickhouseFunnelNew(filter, self.team)
        params = query_builder.params
        query = query_builder.test_query()
        res = sync_execute(query, params)
        self.assertEqual(res[0], (0, 3, 1, 0, 0, 1, 103680.0, 174000.0, 3600.0, 79200.0, 14400.0))

    def test_breakdown_query(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "funnel_window_days": 4,
                "breakdown": "$browser",
                "breakdown_type": "event",
                "events": [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}],
            }
        )
        query_builder = ClickhouseFunnelNew(filter, self.team)
        params = query_builder.params
        query = query_builder.test_query()
        res = sync_execute(query, params)
        self.assertEqual(res[0], (0, 1, 86400.0, "Chrome"), (0, 1, 86400.0, "Safari"))
