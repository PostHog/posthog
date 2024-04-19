from django.conf import settings

DROP_PERFORMANCE_EVENTS_TABLE_MV_SQL = lambda: "DROP TABLE IF EXISTS performance_events_mv ON CLUSTER {cluster}".format(
    cluster=settings.CLICKHOUSE_CLUSTER,
)

DROP_KAFKA_PERFORMANCE_EVENTS_TABLE_SQL = (
    lambda: "DROP TABLE IF EXISTS kafka_performance_events ON CLUSTER {cluster}".format(
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)

DROP_WRITABLE_PERFORMANCE_EVENTS_TABLE_SQL = (
    lambda: "DROP TABLE IF EXISTS writeable_performance_events ON CLUSTER {cluster}".format(
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)
DROP_DISTRIBUTED_PERFORMANCE_EVENTS_TABLE_SQL = (
    lambda: "DROP TABLE IF EXISTS performance_events ON CLUSTER {cluster}".format(
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)
DROP_PERFORMANCE_EVENTS_TABLE_SQL = (
    lambda: "DROP TABLE IF EXISTS sharded_performance_events ON CLUSTER {cluster}".format(
        cluster=settings.CLICKHOUSE_CLUSTER,
    )
)
