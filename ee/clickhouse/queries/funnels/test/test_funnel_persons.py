from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelPersons
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_FUNNEL
from posthog.models import Filter
from posthog.models.filters.mixins.funnel_window_days import FunnelWindowDaysMixin
from posthog.models.person import Person
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


class TestFunnel(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        self._create_sample_data()
        super().setUp()

    def _create_sample_data(self):
        for i in range(250):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-05 00:00:00")

    def test_basic_offset(self):
        data = {
            "insight": INSIGHT_FUNNELS,
            "display": TRENDS_FUNNEL,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        filter = Filter(data=data)
        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()
        self.assertEqual(100, len(results))

        filter_offset = Filter(data={**data, "offset": 100,})
        results = ClickhouseFunnelPersons(filter_offset, self.team).run()
        self.assertEqual(100, len(results))

        filter_offset = Filter(data={**data, "offset": 200,})
        results = ClickhouseFunnelPersons(filter_offset, self.team).run()
        self.assertEqual(50, len(results))

    def test_funnel_window_days_to_microseconds(self):
        one_day = FunnelWindowDaysMixin.microseconds_from_days(1)
        two_days = FunnelWindowDaysMixin.microseconds_from_days(2)
        three_days = FunnelWindowDaysMixin.microseconds_from_days(3)

        self.assertEqual(86_400_000_000, one_day)
        self.assertEqual(17_2800_000_000, two_days)
        self.assertEqual(259_200_000_000, three_days)

    def test_funnel_window_days_to_milliseconds(self):
        one_day = FunnelWindowDaysMixin.milliseconds_from_days(1)
        self.assertEqual(one_day, 86_400_000)

    def test_basic_conversion_window(self):
        data = {
            "insight": INSIGHT_FUNNELS,
            "display": TRENDS_FUNNEL,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        filter = Filter(data={**data, "funnel_window_days": 1,})
        results = ClickhouseFunnel(filter, self.team)._exec_query()
        self.assertEqual(1, len(results))
        self.assertEqual(1, results[0][MAX_STEP_COLUMN])
        self.assertEqual(250, results[0][COUNT_COLUMN])
        self.assertEqual(100, len(results[0][PERSON_ID_COLUMN]))

        filter = Filter(data={**data, "funnel_window_days": 2,})
        results = ClickhouseFunnel(filter, self.team)._exec_query()
        self.assertEqual(1, len(results))
        self.assertEqual(2, results[0][MAX_STEP_COLUMN])
        self.assertEqual(250, results[0][COUNT_COLUMN])
        self.assertEqual(100, len(results[0][PERSON_ID_COLUMN]))
