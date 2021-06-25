from datetime import datetime
from typing import cast
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_trends import ClickhouseFunnelTrendsNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d 00:00:00"

TIME_0 = "2021-06-03 13:42:00"
TIME_1 = "2021-06-07 00:00:00"
TIME_3 = "2021-06-07 19:00:00"
TIME_4 = "2021-06-08 02:00:00"
TIME_99 = "2021-06-13 23:59:59"

STEP_1_EVENT = "step one"
STEP_2_EVENT = "step two"
STEP_3_EVENT = "step three"
USER_A_DISTINCT_ID = "user a"


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelTrendsNew(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def test_no_event_in_period(self):
        _create_person(distinct_ids=[USER_A_DISTINCT_ID], team=self.team)

        _create_event(event=STEP_1_EVENT, distinct_id=USER_A_DISTINCT_ID, team=self.team, timestamp=TIME_0)

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": TIME_1,
                "date_to": TIME_99,
                "funnel_window_days": 7,
                "events": [
                    {"id": STEP_1_EVENT, "order": 0},
                    {"id": STEP_2_EVENT, "order": 1},
                    {"id": STEP_3_EVENT, "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTrendsNew(filter, self.team)
        results = funnel_trends.run()

        self.assertListEqual(
            cast(list, results),
            [
                (datetime(2021, 5, 31, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 1, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 2, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 3, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 4, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 5, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 6, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 7, 0, 0), 0, 0, 0.0),
            ],
        )

    def test_only_one_user_reached_one_step(self):
        _create_person(distinct_ids=[USER_A_DISTINCT_ID], team=self.team)

        _create_event(event=STEP_1_EVENT, distinct_id=USER_A_DISTINCT_ID, team=self.team, timestamp=TIME_3)

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": TIME_1,
                "date_to": TIME_99,
                "funnel_window_days": 7,
                "events": [
                    {"id": STEP_1_EVENT, "order": 0},
                    {"id": STEP_2_EVENT, "order": 1},
                    {"id": STEP_3_EVENT, "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTrendsNew(filter, self.team)
        results = funnel_trends.run()

        self.assertListEqual(
            cast(list, results),
            [
                (datetime(2021, 5, 31, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 1, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 2, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 3, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 4, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 5, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 6, 0, 0), 0, 0, 0.0),
                (datetime(2021, 6, 7, 0, 0), 1, 0, 0.0),
            ],
        )
