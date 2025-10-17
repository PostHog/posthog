from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine, ttl_period
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_HEATMAP_EVENTS
from posthog.session_recordings.sql.session_recording_event_sql import ON_CLUSTER_CLAUSE

HEATMAPS_DATA_TABLE = lambda: "sharded_heatmaps"


"""
We intend to send specific $heatmap events to build a heatmap instead of building from autocapture like the click map
We'll be storing individual clicks per url/team/session
And we'll be querying for those clicks at day level of granularity
And we'll be querying by URL exact or wildcard match
And we'll _sometimes_ be querying by width

We _could_ aggregate this data by day, but we're hoping this will be small/fast enough not to bother
And can always add a materialized view for day (and week?) granularity driven by this data if needed

We only add session_id so that we could offer example sessions for particular clicked areas in the toolbar
"""

KAFKA_HEATMAPS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String)
) ENGINE = {engine}
"""

HEATMAPS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64
) ENGINE = {engine}
"""

HEATMAPS_DATA_TABLE_ENGINE = lambda: MergeTreeEngine("heatmaps", replication_scheme=ReplicationScheme.SHARDED)

HEATMAPS_TABLE_SQL = lambda on_cluster=True: (
    HEATMAPS_TABLE_BASE_SQL
    + """
    PARTITION BY toYYYYMM(timestamp)
    -- almost always this is being queried by
    --   * type,
    --   * team_id,
    --   * date range,
    --   * URL (maybe matching wild cards),
    --   * width
    -- we'll almost never query this by session id
    -- so from least to most cardinality that's
    ORDER BY (type, team_id,  toDate(timestamp), current_url, viewport_width)
    {ttl_period}
-- I am purposefully not setting index granularity
-- the default is 8192, and we will be loading a lot of data
-- per query, we tend to copy this 512 around the place but
-- i don't think it applies here
"""
).format(
    table_name=HEATMAPS_DATA_TABLE(),
    on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    engine=HEATMAPS_DATA_TABLE_ENGINE(),
    ttl_period=ttl_period("timestamp", 90, unit="DAY"),
)

KAFKA_HEATMAPS_TABLE_SQL = lambda: KAFKA_HEATMAPS_TABLE_BASE_SQL.format(
    table_name="kafka_heatmaps",
    engine=kafka_engine(topic=KAFKA_CLICKHOUSE_HEATMAP_EVENTS),
)

HEATMAPS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS heatmaps_mv
TO {database}.{target_table}
AS SELECT
    session_id,
    team_id,
    distinct_id,
    timestamp,
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y,
    -- stored so that in future we can support other resolutions
    scale_factor,
    viewport_width,
    viewport_height,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed,
    current_url,
    type,
    _timestamp,
    _offset,
    _partition
FROM {database}.kafka_heatmaps
""".format(
        target_table="writable_heatmaps",
        database=settings.CLICKHOUSE_DATABASE,
    )
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_heatmaps based on a sharding key.
WRITABLE_HEATMAPS_TABLE_SQL = lambda: HEATMAPS_TABLE_BASE_SQL.format(
    table_name="writable_heatmaps",
    engine=Distributed(
        data_table=HEATMAPS_DATA_TABLE(),
        sharding_key="cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp))))",
    ),
)

# This table is responsible for reading from heatmaps on a cluster setting
DISTRIBUTED_HEATMAPS_TABLE_SQL = lambda: HEATMAPS_TABLE_BASE_SQL.format(
    table_name="heatmaps",
    engine=Distributed(
        data_table=HEATMAPS_DATA_TABLE(),
        sharding_key="cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp))))",
    ),
)

DROP_HEATMAPS_TABLE_SQL = lambda: (f"DROP TABLE IF EXISTS {HEATMAPS_DATA_TABLE()}")

DROP_WRITABLE_HEATMAPS_TABLE_SQL = lambda: (f"DROP TABLE IF EXISTS writable_heatmaps")

DROP_HEATMAPS_TABLE_MV_SQL = lambda: (f"DROP TABLE IF EXISTS heatmaps_mv")

DROP_KAFKA_HEATMAPS_TABLE_SQL = lambda: (f"DROP TABLE IF EXISTS kafka_heatmaps")

TRUNCATE_HEATMAPS_TABLE_SQL = lambda: (f"TRUNCATE TABLE IF EXISTS {HEATMAPS_DATA_TABLE()}")

ALTER_TABLE_ADD_TTL_PERIOD = lambda: (
    f"ALTER TABLE {HEATMAPS_DATA_TABLE()} MODIFY {ttl_period('timestamp', 90, unit='DAY')}"
)
