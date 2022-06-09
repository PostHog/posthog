from ee.clickhouse.queries.paths.paths_event_query import ClickhousePathEventQuery
from posthog.queries.paths.paths import Paths


class ClickhousePaths(Paths):
    event_query = ClickhousePathEventQuery
