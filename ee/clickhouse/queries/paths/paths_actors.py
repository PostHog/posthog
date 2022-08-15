from ee.clickhouse.queries.paths.paths import ClickhousePaths
from posthog.queries.paths.paths_actors import PathsActors


class ClickhousePathsActors(PathsActors, ClickhousePaths):  # type: ignore
    pass
