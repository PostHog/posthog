from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.person import Person
from posthog.queries.test.test_retention import retention_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseRetention(ClickhouseTestMixin, retention_test_factory(ClickhouseRetention, _create_event, Person.objects.create)):  # type: ignore

    # override original test
    def test_retention_with_properties(self):
        pass

    # override original test
    def test_retention_action_start_point(self):
        pass
