from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person
from ee.clickhouse.queries.clickhouse_funnel import ClickhouseFunnel
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.test.test_funnel import funnel_test_factory


class TestClickhouseFunnel(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnel, create_event, create_person)):  # type: ignore
    pass
