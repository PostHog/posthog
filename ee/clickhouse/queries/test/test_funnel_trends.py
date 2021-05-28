from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_funnel_trends import ClickhouseFunnelTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import FILTER_TEST_ACCOUNTS, INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnelTrends(ClickhouseTestMixin, APIBaseTest):  # type: ignore
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

        # user_one, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_one", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_one", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_one", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_two, funnel steps: one, two
        _create_event(event="step one", distinct_id="user_two", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_two", team=self.team, timestamp="2021-05-04 00:00:00")

        # user_three, funnel steps: one
        _create_event(event="step one", distinct_id="user_three", team=self.team, timestamp="2021-05-06 00:00:00")

        # user_four, funnel steps: none
        _create_event(event="step none", distinct_id="user_four", team=self.team, timestamp="2021-05-06 00:00:00")

        # user_five, funnel steps: one, two, three in the same day
        _create_event(event="step one", distinct_id="user_five", team=self.team, timestamp="2021-05-01 01:00:00")
        _create_event(event="step two", distinct_id="user_five", team=self.team, timestamp="2021-05-01 02:00:00")
        _create_event(event="step three", distinct_id="user_five", team=self.team, timestamp="2021-05-01 03:00:00")

        # user_six, funnel steps: one, two three
        _create_event(event="step one", distinct_id="user_six", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_six", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_six", team=self.team, timestamp="2021-05-05 00:00:00")

        # user_seven, funnel steps: one, two
        _create_event(event="step one", distinct_id="user_seven", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="user_seven", team=self.team, timestamp="2021-05-04 00:00:00")

    def test_milliseconds_from_days_conversion(self):
        self.assertEqual(ClickhouseFunnelTrends._milliseconds_from_days(1), 86400000)

    def test_raw_query(self):
        one_day_in_milliseconds = ClickhouseFunnelTrends._milliseconds_from_days(1)

        query_filter_params = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "sign up", "order": 0}, {"id": "pay", "order": 1},],
            }
        )

        results = ClickhouseFunnelTrends().run(self.team, filter=Filter(query_filter_params))
        # {
        #     "start_timestamp": "2021-05-01 00:00:00",
        #     "end_timestamp": "2021-05-07 00:00:00",
        #     "team_id": self.team.id,
        #     "steps": "event = 'step one', event = 'step two', event = 'step three'",
        #     "window_in_milliseconds": one_day_in_milliseconds,
        # }

        self.assertEqual(len(results), 4)
