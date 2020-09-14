from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.test.test_stickiness import stickiness_test_factory


class TestClickhouseStickiness(ClickhouseTestMixin, stickiness_test_factory(ClickhouseStickiness, create_event, create_person)):  # type: ignore
    pass
