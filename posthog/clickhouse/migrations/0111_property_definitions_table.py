from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.client.connection import NodeRole
from posthog.settings.data_stores import POSTHOG_MIGRATION_CLUSTER

PROPERTY_DEFINITIONS_TABLE_SQL = f"""
CREATE TABLE property_definitions
(
    -- Team and project relationships
    team_id UInt32,
    project_id UInt32 NULL,

    -- Core property fields
    name String,
    property_type String NULL,
    event String NULL, -- Only null for non-event types
    group_type_index UInt8 NULL,

    -- Type enum (1=event, 2=person, 3=group, 4=session)
    type UInt8 DEFAULT 1,

    -- Metadata
    last_seen_at DateTime,

    -- A composite version number that prioritizes property_type presence over timestamp
    -- We negate isNull() so rows WITH property_type get higher preference
    version UInt64 MATERIALIZED (bitShiftLeft(toUInt64(NOT isNull(property_type)), 48) + toUInt64(toUnixTimestamp(last_seen_at)))
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog_migrations.property_definitions', '{{replica}}-{{shard}}', version)
ORDER BY (team_id, type, COALESCE(event, ''), name, COALESCE(group_type_index, 255))
SETTINGS index_granularity = 8192
"""

operations = [
    run_sql_with_exceptions(PROPERTY_DEFINITIONS_TABLE_SQL, node_role=NodeRole.ALL),
]
