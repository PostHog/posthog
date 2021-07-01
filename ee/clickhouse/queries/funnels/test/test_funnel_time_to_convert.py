from datetime import datetime, timedelta
from uuid import uuid4

import pytz

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_time_to_convert import ClickhouseFunnelTimeToConvert
from ee.clickhouse.queries.funnels.funnel_trends import ClickhouseFunnelTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d %H:%M:%S"
FORMAT_TIME_DAY_END = "%Y-%m-%d 23:59:59"


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelTrends(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def test_basic(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-08 18:00:00")
        _create_event(event="step two", distinct_id="user a", team=self.team, timestamp="2021-06-08 19:00:00")
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-08 21:00:00")

        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:00:00")
        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:37:00")

        _create_event(event="step one", distinct_id="user c", team=self.team, timestamp="2021-06-11 07:00:00")
        _create_event(event="step two", distinct_id="user c", team=self.team, timestamp="2021-06-12 06:00:00")

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team)
        results = funnel_trends.run()

        # Autobinned using the maximum time to convert
        # Since the maximum time to step 1 from 0 is user C's 23 h (82_800 s) and the number of bins is 10,
        # each bin is an interval of 8280 s, starting with 0, left-inclusive
        self.assertEqual(
            results,
            [
                (8280.0, 2),  # Reached step 1 from step 0 in less than 8280 s - users A and B fall into this bin
                (16560.0, 0),  # Reached step 1 from step 0 in at least 8280 s but less than 16_560 s - no users
                (24840.0, 0),  # And so on
                (33120.0, 0),
                (41400.0, 0),
                (49680.0, 0),
                (57960.0, 0),
                (66240.0, 0),
                (74520.0, 0),
                (82800.0, 0),
                (91080.0, 1),  # >= 82_800 && < 91_080 - user C falls into this bin, with a time of exactly 82_800 s
            ],
        )
