from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_funnel import ClickhouseFunnel
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.person import Person
from posthog.queries.test.test_funnel import funnel_test_factory


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class TestClickhouseFunnel(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnel, create_event, _create_person)):  # type: ignore
    pass
