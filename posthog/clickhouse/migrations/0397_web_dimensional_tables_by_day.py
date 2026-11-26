from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_bounces_dimensional_preaggregated_sql import (
    DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_BY_DAY_TABLE_SQL,
    SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_BY_DAY_TABLE_SQL,
)
from posthog.clickhouse.preaggregation.web_stats_dimensional_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_BY_DAY_TABLE_SQL,
    SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_BY_DAY_TABLE_SQL,
)

# The storage tables live on AUX, as the current dimensional tables do. The Distributed read tables go on every role
# whose nodes run web analytics reads: DATA, AUX for ad-hoc reads, and the events cluster (INGESTION_EVENTS), which
# serves every query of a project that reads events_json. A read table missing from the events cluster breaks those
# projects' dimensional reads.
operations = [
    *(
        run_sql_with_exceptions(sql(), node_roles=[NodeRole.AUX], sharded=True)
        for sql in (
            SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_BY_DAY_TABLE_SQL,
            SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_BY_DAY_TABLE_SQL,
        )
    ),
    *(
        run_sql_with_exceptions(sql(), node_roles=[role])
        for role in (NodeRole.DATA, NodeRole.AUX, NodeRole.INGESTION_EVENTS)
        for sql in (
            DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_BY_DAY_TABLE_SQL,
            DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_BY_DAY_TABLE_SQL,
        )
    ),
]
