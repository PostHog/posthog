from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel, ClickhouseFunnelNew
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters.filter import Filter
from posthog.models.person import Person
from posthog.queries.test.test_funnel import funnel_test_factory

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


class TestFunnelNew(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnelNew, _create_event, _create_person)):  # type: ignore
    def _create_sample_data(self):
        # five people, three steps
        _create_person(distinct_ids=["user_one"], team=self.team)
        _create_person(distinct_ids=["user_two"], team=self.team)
        _create_person(distinct_ids=["user_three"], team=self.team)
        _create_person(distinct_ids=["user_four"], team=self.team)

        # user_one, funnel steps: one, two three
        _create_event(
            event="step one",
            distinct_id="user_one",
            team=self.team,
            timestamp="2021-05-01 00:00:00",
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

        # user_two, funnel steps: one, two
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
            timestamp="2021-05-04 00:00:00",
            properties={"$browser": "Safari"},
        )

        # user_three, funnel steps: one
        _create_event(
            event="step one",
            distinct_id="user_three",
            team=self.team,
            timestamp="2021-05-06 00:00:00",
            properties={"$browser": "Chrome"},
        )

        # user_four, funnel steps: one
        _create_event(event="step one", distinct_id="user_four", team=self.team, timestamp="2021-05-06 00:00:00")

    # def test_funnel_step_timing(self):
    #     pass

    # def test_funnel_step_repeated_steps(self):
    #     # step X -> step Y -> step Y
    #     pass

    # def test_funnel_step_repeated_first_step(self):
    #     # step X -> step X -> step Y
    #     pass

    # def test_funnel_step_all_repeated(self):
    #     # step X -> step X -> step X
    #     pass

    # def test_breakdown_basic_query(self):
    #     self._create_sample_data()
    #     filter = Filter(
    #         data={
    #             "insight": INSIGHT_FUNNELS,
    #             "date_from": "2021-05-01 00:00:00",
    #             "date_to": "2021-05-07 00:00:00",
    #             "funnel_window_days": 4,
    #             "breakdown": "$browser",
    #             "breakdown_type": "event",
    #             "events": [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}],
    #         }
    #     )
    #     res = ClickhouseFunnelNew(filter, self.team).run()
    #     self.assertEqual(res[0], (0, 1, 86400.0, "Chrome"), (0, 1, 86400.0, "Safari"))

    # def test_breakdown_limit(self):
    #     # decide how to handle properties that have hundreds of values
    #     pass

    # def test_breakdown_step_timing(self):
    #     pass

    # def test_conversion_window(self):
    #    pass
