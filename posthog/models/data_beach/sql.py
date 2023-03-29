from django.conf import settings
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

# NOTE: the below table is only for append only data. Append only means we can
# make certain assumptions about the schema.
CREATE_DATA_BEACH_APPENDABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`data_beach_appendable`
    ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
        team_id INT NOT NULL,
        table_name String NOT NULL,
        -- An id that we consider to uniquely identify the row, for the
        -- specified team_id and table_name.
        id String NOT NULL,
        -- We add the data block just as a string, which we'll parse with
        -- JSONExtract when querying.
        data String NOT NULL,
        -- Add a timestamp to the data for purposes of debugging. It's also
        -- plausible that we'd want to use this e.g. for selecting the latest
        -- version of the data.
        created_at DateTime64(6, 'UTC') DEFAULT now()
    )
    ENGINE = ReplicatedReplacingMergeTree(
        -- NOTE: for testing we use a uuid to ensure that we don't get conflicts
        -- when the tests tear down and recreate the table.
        '/clickhouse/tables/{'{uuid}' if settings.TEST else ''}noshard/{CLICKHOUSE_DATABASE}.data_beach_appendable',
        '{{replica}}-{{shard}}',
        -- Use the created_at as a proxy for what we think is the latest version
        -- of the data. This is a bit of a hack, but it's the best we can do
        -- without adding a version column.
        created_at
    )
    -- NOTE: we partition by year month, which makes sense for an append only
    -- table but may not make sense for, e.g. a table that we want to e.g. delete
    -- or update rows.
    PARTITION BY toYYYYMM(created_at)
    -- We order by team_id, table_name such that we colocate data that will be
    -- queried at the same time is likely on the same part, i.e. so we don't need
    -- to read the entirety of the parts every time. We include the id such that,
    -- e.g. if we wanted to provide delete functionality that we can colocate the
    -- data and the tombstone data such that when merges occur they will be able
    -- to only keep the latest version.
    ORDER BY (team_id, table_name, id)
    COMMENT 'A table to store append only data for the Data Beach project.'
"""
