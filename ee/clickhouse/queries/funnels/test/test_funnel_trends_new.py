from datetime import date, datetime, timedelta
from typing import Union, cast
from uuid import uuid4

from ee.clickhouse.client import format_sql, sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_trends import ClickhouseFunnelTrendsNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.filters import Filter
from posthog.models.filters.mixins.funnel_window_days import FunnelWindowDaysMixin
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


class TestFunnelTrends(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def test_returns(self):
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "hour",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTrendsNew(filter, self.team)
        results = funnel_trends.run()
