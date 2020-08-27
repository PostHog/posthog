from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.test.test_stickiness import stickiness_test_factory


# class TestClickhouseStickiness(ClickhouseTestMixin, stickiness_test_factory(ClickhouseStickiness)):
class TestClickhouseStickiness:
    pass
