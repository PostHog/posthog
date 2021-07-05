from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_time_to_convert import ClickhouseFunnelTimeToConvert
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
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

    def test_auto_bin_count(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-08 18:00:00")
        _create_event(event="step two", distinct_id="user a", team=self.team, timestamp="2021-06-08 19:00:00")
        # Converted from 0 to 1 in 3600 s
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-08 21:00:00")

        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:00:00")
        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:37:00")
        # Converted from 0 to 1 in 2200 s

        _create_event(event="step one", distinct_id="user c", team=self.team, timestamp="2021-06-11 07:00:00")
        _create_event(event="step two", distinct_id="user c", team=self.team, timestamp="2021-06-12 06:00:00")
        # Converted from 0 to 1 in 82_800 s

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
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

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            [
                (2220.0, 2),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                (29080.0, 0),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                (55940.0, 0),  # Same as above
                (82800.0, 1),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
            ],
        )

    def test_custom_bin_count(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(event="step one", distinct_id="user a", team=self.team, timestamp="2021-06-08 18:00:00")
        _create_event(event="step two", distinct_id="user a", team=self.team, timestamp="2021-06-08 19:00:00")
        # Converted from 0 to 1 in 3600 s
        _create_event(event="step three", distinct_id="user a", team=self.team, timestamp="2021-06-08 21:00:00")

        _create_event(event="step one", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:00:00")
        _create_event(event="step two", distinct_id="user b", team=self.team, timestamp="2021-06-09 13:37:00")
        # Converted from 0 to 1 in 2200 s

        _create_event(event="step one", distinct_id="user c", team=self.team, timestamp="2021-06-11 07:00:00")
        _create_event(event="step two", distinct_id="user c", team=self.team, timestamp="2021-06-12 06:00:00")
        # Converted from 0 to 1 in 82_800 s

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "bin_count": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team)
        results = funnel_trends.run()

        # 7 bins, autoscaled to work best with minimum time to convert and maximum time to convert at hand
        self.assertEqual(
            results,
            [
                (2220.0, 2),  # Reached step 1 from step 0 in at least 2200 s but less than 13_732 s - users A and B
                (13732.0, 0),  # Analogous to above, just an interval (in this case 13_732 s) up - no users
                (25244.0, 0),  # And so on
                (36756.0, 0),
                (48268.0, 0),
                (59780.0, 0),
                (71292.0, 1),  # Reached step 1 from step 0 in at least 71_292 s but less than 82_804 s - user C
                (82804.0, 0),
            ],
        )
