from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.paths.paths import ClickhousePaths


class ClickhousePathsActors(ClickhousePaths, ActorBaseQuery):  # type: ignore
    pass
