from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.paths.paths import ClickhousePaths
from posthog.queries.paths.paths_actors import PathsActors


class ClickhousePathsActors(ActorBaseQuery, PathsActors, ClickhousePaths):  # type: ignore
    pass
