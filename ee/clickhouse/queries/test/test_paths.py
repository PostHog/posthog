from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.test.test_paths import paths_test_factory


class TestClickhousePaths(ClickhouseTestMixin, paths_test_factory(ClickhousePaths, create_event, create_person)):  # type: ignore
    pass
