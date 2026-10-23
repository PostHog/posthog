from functools import cache

from posthog import settings
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.run_mode import run_mode
from posthog.settings.data_stores import (
    CLICKHOUSE_CLUSTER,
    CLICKHOUSE_MIGRATIONS_CLUSTER,
    CLICKHOUSE_MIGRATIONS_HOST,
    CLICKHOUSE_SATELLITE_CLUSTERS,
)


@cache
def get_migrations_cluster() -> ClickhouseCluster:
    return get_cluster(
        host=CLICKHOUSE_MIGRATIONS_HOST,
        cluster=CLICKHOUSE_MIGRATIONS_CLUSTER,
        data_cluster=CLICKHOUSE_CLUSTER,
        satellite_clusters=CLICKHOUSE_SATELLITE_CLUSTERS or None,
        ch_user=ClickHouseUser.MIGRATIONS,
    )


def collapses_to_all_nodes() -> bool:
    return settings.E2E_TESTING or not run_mode().is_deployed_cloud
