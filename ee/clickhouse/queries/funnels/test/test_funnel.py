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


class TestFunnelNew(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnelNew, _create_event, _create_person)):
    pass
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
