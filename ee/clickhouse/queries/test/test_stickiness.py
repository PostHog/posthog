from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from posthog.queries.test.test_stickiness import stickiness_test_factory


class TestClickhouseStickiness(stickiness_test_factory(ClickhouseStickiness)):
    pass
