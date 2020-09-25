from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.person import Person
from posthog.queries.test.test_paths import paths_test_factory


def _create_event(**kwargs):
    create_event(**kwargs, event_uuid=uuid4())


class TestClickhousePaths(ClickhouseTestMixin, paths_test_factory(ClickhousePaths, _create_event, Person.objects.create)):  # type: ignore
    pass
