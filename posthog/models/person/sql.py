from django.conf import settings

from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, KAFKA_COLUMNS_WITH_PARTITION, STORAGE_POLICY, kafka_engine
from posthog.clickhouse.table_engines import CollapsingMergeTree, Distributed, ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID, KAFKA_PERSON_UNIQUE_ID

TRUNCATE_PERSON_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS person {ON_CLUSTER_CLAUSE()}"

DROP_PERSON_TABLE_SQL = f"DROP TABLE IF EXISTS person {ON_CLUSTER_CLAUSE()}"

TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS person_distinct_id {ON_CLUSTER_CLAUSE()}"
TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS person_distinct_id2 {ON_CLUSTER_CLAUSE()}"

PERSONS_TABLE = "person"
PERSONS_TABLE_MV = f"{PERSONS_TABLE}_mv"
PERSONS_WRITABLE_TABLE = f"writable_{PERSONS_TABLE}"
KAFKA_PERSONS_TABLE = f"kafka_{PERSONS_TABLE}"

DROP_PERSONS_TABLE_MV_SQL = f"DROP TABLE IF EXISTS {PERSONS_TABLE_MV}"
DROP_KAFKA_PERSONS_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_PERSONS_TABLE}"

PERSONS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8,
    version UInt64
    {extra_fields}
) ENGINE = {engine}
"""


def PERSONS_TABLE_ENGINE():
    return ReplacingMergeTree(PERSONS_TABLE, ver="version")


def PERSONS_TABLE_SQL(on_cluster=True):
    return (
        PERSONS_TABLE_BASE_SQL
        + """ORDER BY (team_id, id)
{storage_policy}
"""
    ).format(
        table_name=PERSONS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=PERSONS_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS}
    , {index_by_kafka_timestamp(PERSONS_TABLE)}
    """,
        storage_policy=STORAGE_POLICY(),
    )


def KAFKA_PERSONS_TABLE_SQL(on_cluster=True):
    return PERSONS_TABLE_BASE_SQL.format(
        table_name=KAFKA_PERSONS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(KAFKA_PERSON),
        extra_fields="",
    )


def PERSONS_TABLE_MV_SQL(on_cluster=True, target_table=PERSONS_WRITABLE_TABLE):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
AS SELECT
id,
created_at,
team_id,
properties,
is_identified,
is_deleted,
version,
_timestamp,
_offset
FROM {kafka_table}
""".format(
        mv_name=PERSONS_TABLE_MV,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        target_table=target_table,
        kafka_table=KAFKA_PERSONS_TABLE,
    )


def PERSONS_WRITABLE_TABLE_SQL():
    return PERSONS_TABLE_BASE_SQL.format(
        table_name=PERSONS_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=PERSONS_TABLE, cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER),
        extra_fields=KAFKA_COLUMNS,
    )


GET_LATEST_PERSON_SQL = """
SELECT * FROM person JOIN (
    SELECT id, max(version) as version, max(is_deleted) as is_deleted
    FROM person
    WHERE team_id = %(team_id)s
    GROUP BY id
) as person_max ON person.id = person_max.id AND person.version = person_max.version
WHERE team_id = %(team_id)s
  AND person_max.is_deleted = 0
  {query}
"""

GET_LATEST_PERSON_ID_SQL = """
(select id from (
    {latest_person_sql}
))
""".format(latest_person_sql=GET_LATEST_PERSON_SQL)

#
# person_distinct_id - legacy table for person distinct IDs, do not use
#


PERSONS_DISTINCT_ID_TABLE = "person_distinct_id"

PERSONS_DISTINCT_ID_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Int8 DEFAULT 1,
    is_deleted Int8 ALIAS if(_sign==-1, 1, 0)
    {extra_fields}
) ENGINE = {engine}
"""


def PERSONS_DISTINCT_ID_TABLE_SQL(on_cluster=True):
    return (
        PERSONS_DISTINCT_ID_TABLE_BASE_SQL
        + """Order By (team_id, distinct_id, person_id)
{storage_policy}
"""
    ).format(
        table_name=PERSONS_DISTINCT_ID_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=CollapsingMergeTree(PERSONS_DISTINCT_ID_TABLE, ver="_sign"),
        extra_fields=KAFKA_COLUMNS,
        storage_policy=STORAGE_POLICY(),
    )


# :KLUDGE: We default is_deleted to 0 for backwards compatibility for when we drop `is_deleted` from message schema.
#    Can't make DEFAULT if(_sign==-1, 1, 0) because Cyclic aliases error.
KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL = (
    lambda on_cluster=True: """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Nullable(Int8),
    is_deleted Nullable(Int8)
) ENGINE = {engine}
""".format(
        table_name="kafka_" + PERSONS_DISTINCT_ID_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(KAFKA_PERSON_UNIQUE_ID),
    )
)


# You must include the database here because of a bug in clickhouse
# related to https://github.com/ClickHouse/ClickHouse/issues/10471
def PERSONS_DISTINCT_ID_TABLE_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name}_mv ON CLUSTER '{cluster}'
TO {database}.{table_name}
AS SELECT
distinct_id,
person_id,
team_id,
coalesce(_sign, if(is_deleted==0, 1, -1)) AS _sign,
_timestamp,
_offset
FROM {database}.kafka_{table_name}
""".format(
        table_name=PERSONS_DISTINCT_ID_TABLE,
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )


#
# person_distinct_id2 - table currently used for person distinct IDs, its schema is improved over the original
#

PERSON_DISTINCT_ID2_TABLE = "person_distinct_id2"
PERSON_DISTINCT_ID2_TABLE_MV = f"{PERSON_DISTINCT_ID2_TABLE}_mv"
PERSON_DISTINCT_ID2_WRITABLE_TABLE = f"writable_{PERSON_DISTINCT_ID2_TABLE}"
KAFKA_PERSON_DISTINCT_ID2_TABLE = f"kafka_{PERSON_DISTINCT_ID2_TABLE}"

DROP_KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_PERSON_DISTINCT_ID2_TABLE}"
DROP_PERSON_DISTINCT_ID2_TABLE_MV_SQL = f"DROP TABLE IF EXISTS {PERSON_DISTINCT_ID2_TABLE_MV}"

# NOTE: This table base SQL is also used for distinct ID overrides!
PERSON_DISTINCT_ID2_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    {extra_fields}
) ENGINE = {engine}
"""


def PERSON_DISTINCT_ID2_TABLE_ENGINE():
    return ReplacingMergeTree(PERSON_DISTINCT_ID2_TABLE, ver="version")


def PERSON_DISTINCT_ID2_TABLE_SQL(on_cluster=True):
    return (
        PERSON_DISTINCT_ID2_TABLE_BASE_SQL
        + """
    ORDER BY (team_id, distinct_id)
    SETTINGS index_granularity = 512
    """
    ).format(
        table_name=PERSON_DISTINCT_ID2_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=PERSON_DISTINCT_ID2_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS}
    , _partition UInt64
    , {index_by_kafka_timestamp(PERSON_DISTINCT_ID2_TABLE)}
    """,
    )


def KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL(on_cluster=True):
    return PERSON_DISTINCT_ID2_TABLE_BASE_SQL.format(
        table_name=KAFKA_PERSON_DISTINCT_ID2_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(KAFKA_PERSON_DISTINCT_ID),
        extra_fields="",
    )


def PERSON_DISTINCT_ID2_MV_SQL(on_cluster=True, target_table=PERSON_DISTINCT_ID2_WRITABLE_TABLE):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
AS SELECT
team_id,
distinct_id,
person_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {kafka_table}
""".format(
        mv_name=PERSON_DISTINCT_ID2_TABLE_MV,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        target_table=target_table,
        kafka_table=KAFKA_PERSON_DISTINCT_ID2_TABLE,
    )


def PERSON_DISTINCT_ID2_WRITABLE_TABLE_SQL():
    # This is a table used for writing from the ingestion layer. It's not sharded, thus it uses the single shard cluster.
    return PERSON_DISTINCT_ID2_TABLE_BASE_SQL.format(
        table_name=PERSON_DISTINCT_ID2_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(data_table=PERSON_DISTINCT_ID2_TABLE, cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    """,
    )


#
# person_distinct_id_overrides: This table contains rows for all (team_id,
# distinct_id) pairs where the person_id has changed and those updates have not
# yet been integrated back into the events table via squashing.
#


PERSON_DISTINCT_ID_OVERRIDES_TABLE = "person_distinct_id_overrides"
PERSON_DISTINCT_ID_OVERRIDES_TABLE_MV = f"{PERSON_DISTINCT_ID_OVERRIDES_TABLE}_mv"
PERSON_DISTINCT_ID_OVERRIDES_WRITABLE_TABLE = f"writable_{PERSON_DISTINCT_ID_OVERRIDES_TABLE}"
KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE = f"kafka_{PERSON_DISTINCT_ID_OVERRIDES_TABLE}"

DROP_KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE}"
DROP_PERSON_DISTINCT_ID_OVERRIDES_TABLE_MV_SQL = f"DROP TABLE IF EXISTS {PERSON_DISTINCT_ID_OVERRIDES_TABLE_MV}"

PERSON_DISTINCT_ID_OVERRIDES_TABLE_BASE_SQL = PERSON_DISTINCT_ID2_TABLE_BASE_SQL


def PERSON_DISTINCT_ID_OVERRIDES_TABLE_ENGINE():
    return ReplacingMergeTree(PERSON_DISTINCT_ID_OVERRIDES_TABLE, ver="version")


def PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL(on_cluster=True):
    return (
        PERSON_DISTINCT_ID_OVERRIDES_TABLE_BASE_SQL
        + """
    ORDER BY (team_id, distinct_id)
    SETTINGS index_granularity = 512
    """
    ).format(
        table_name=PERSON_DISTINCT_ID_OVERRIDES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=PERSON_DISTINCT_ID_OVERRIDES_TABLE_ENGINE(),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    , {index_by_kafka_timestamp(PERSON_DISTINCT_ID_OVERRIDES_TABLE)}
    """,
    )


KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL = (
    lambda on_cluster=True: PERSON_DISTINCT_ID_OVERRIDES_TABLE_BASE_SQL.format(
        table_name=KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(KAFKA_PERSON_DISTINCT_ID, group="clickhouse-person-distinct-id-overrides"),
        extra_fields="",
    )
)


def PERSON_DISTINCT_ID_OVERRIDES_MV_SQL(on_cluster=True, target_table=PERSON_DISTINCT_ID_OVERRIDES_WRITABLE_TABLE):
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {target_table}
AS SELECT
team_id,
distinct_id,
person_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {kafka_table}
WHERE version > 0 -- only store updated rows, not newly inserted ones
""".format(
        mv_name=PERSON_DISTINCT_ID_OVERRIDES_TABLE_MV,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        target_table=target_table,
        kafka_table=KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE,
    )


def PERSON_DISTINCT_ID_OVERRIDES_WRITABLE_TABLE_SQL():
    # This is a table used for writing from the ingestion layer. It's not sharded, thus it uses the single shard cluster.
    return PERSON_DISTINCT_ID_OVERRIDES_TABLE_BASE_SQL.format(
        table_name=PERSON_DISTINCT_ID_OVERRIDES_WRITABLE_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=Distributed(
            data_table=PERSON_DISTINCT_ID_OVERRIDES_TABLE, cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER
        ),
        extra_fields=f"""
    {KAFKA_COLUMNS_WITH_PARTITION}
    """,
    )


def TRUNCATE_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {PERSON_DISTINCT_ID_OVERRIDES_TABLE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"


#
# Static Cohort
#

PERSON_STATIC_COHORT_TABLE = "person_static_cohort"
PERSON_STATIC_COHORT_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    id UUID,
    person_id UUID,
    cohort_id Int64,
    team_id Int64
    {extra_fields}
) ENGINE = {engine}
"""


def PERSON_STATIC_COHORT_TABLE_ENGINE():
    return ReplacingMergeTree(PERSON_STATIC_COHORT_TABLE, ver="_timestamp")


def PERSON_STATIC_COHORT_TABLE_SQL(on_cluster=True):
    return (
        PERSON_STATIC_COHORT_BASE_SQL
        + """Order By (team_id, cohort_id, person_id, id)
{storage_policy}
"""
    ).format(
        table_name=PERSON_STATIC_COHORT_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=PERSON_STATIC_COHORT_TABLE_ENGINE(),
        storage_policy=STORAGE_POLICY(),
        extra_fields=KAFKA_COLUMNS,
    )


def TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {PERSON_STATIC_COHORT_TABLE} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"


INSERT_PERSON_STATIC_COHORT = (
    f"INSERT INTO {PERSON_STATIC_COHORT_TABLE} (id, person_id, cohort_id, team_id, _timestamp) VALUES"
)

DELETE_PERSON_FROM_STATIC_COHORT = f"DELETE FROM {PERSON_STATIC_COHORT_TABLE} WHERE person_id = %(person_id)s AND cohort_id = %(cohort_id)s AND team_id = %(team_id)s"

#
# Copying demo data
#

COPY_PERSONS_BETWEEN_TEAMS = COPY_ROWS_BETWEEN_TEAMS_BASE_SQL.format(
    table_name=PERSONS_TABLE,
    columns_except_team_id="""id, created_at, properties, is_identified, _timestamp, _offset, is_deleted""",
)

COPY_PERSON_DISTINCT_ID2S_BETWEEN_TEAMS = COPY_ROWS_BETWEEN_TEAMS_BASE_SQL.format(
    table_name=PERSON_DISTINCT_ID2_TABLE,
    columns_except_team_id="""distinct_id, person_id, is_deleted, version, _timestamp, _offset, _partition""",
)

SELECT_PERSONS_OF_TEAM = """
SELECT id, created_at, properties, is_identified, version
FROM {table_name}
WHERE team_id = %(source_team_id)s
""".format(table_name=PERSONS_TABLE)

SELECT_PERSON_DISTINCT_ID2S_OF_TEAM = """SELECT * FROM {table_name} WHERE team_id = %(source_team_id)s""".format(
    table_name=PERSON_DISTINCT_ID2_TABLE
)

#
# Other queries
#

# `relevant_events_filter`` in the form of "AND event IN (...)" allows us to cut down memory usage by a lot at scale
GET_TEAM_PERSON_DISTINCT_IDS = """
SELECT distinct_id, argMax(person_id, version) as person_id
FROM person_distinct_id2
WHERE team_id = %(team_id)s
{relevant_events_filter}
GROUP BY distinct_id
HAVING argMax(is_deleted, version) = 0
"""

GET_PERSON_IDS_BY_FILTER = """
SELECT DISTINCT p.id
FROM ({latest_person_sql}) AS p
INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS pdi ON p.id = pdi.person_id
WHERE team_id = %(team_id)s
  {distinct_query}
{limit}
{offset}
""".format(
    latest_person_sql=GET_LATEST_PERSON_SQL,
    distinct_query="{distinct_query}",
    limit="{limit}",
    offset="{offset}",
    GET_TEAM_PERSON_DISTINCT_IDS="{GET_TEAM_PERSON_DISTINCT_IDS}",
)

INSERT_PERSON_SQL = """
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version) SELECT %(id)s, %(created_at)s, %(team_id)s, %(properties)s, %(is_identified)s, %(_timestamp)s, 0, %(is_deleted)s, %(version)s
"""

INSERT_PERSON_BULK_SQL = """
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version) VALUES
"""

INSERT_PERSON_DISTINCT_ID2 = """
INSERT INTO person_distinct_id2 (distinct_id, person_id, team_id, is_deleted, version, _timestamp, _offset, _partition) SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, %(is_deleted)s, %(version)s, now(), 0, 0 VALUES
"""

BULK_INSERT_PERSON_DISTINCT_ID2 = """
INSERT INTO person_distinct_id2 (distinct_id, person_id, team_id, is_deleted, version, _timestamp, _offset, _partition) VALUES
"""


INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID = """
INSERT INTO {cohort_table} SELECT generateUUIDv4(), actor_id, %(cohort_id)s, %(team_id)s, %(_timestamp)s, 0 FROM (
    SELECT DISTINCT actor_id FROM ({query})
)
"""

INSERT_COHORT_ALL_PEOPLE_SQL = """
INSERT INTO {cohort_table} SELECT generateUUIDv4(), id, %(cohort_id)s, %(team_id)s, %(_timestamp)s, 0 FROM (
    SELECT id FROM (
        {latest_person_sql}
    ) as person INNER JOIN (
        SELECT person_id, distinct_id FROM ({GET_TEAM_PERSON_DISTINCT_IDS}) WHERE person_id IN ({content_sql})
    ) as pdi ON person.id = pdi.person_id
    WHERE team_id = %(team_id)s
    GROUP BY id
)
"""

GET_DISTINCT_IDS_BY_PROPERTY_SQL = """
SELECT distinct_id
FROM (
    {GET_TEAM_PERSON_DISTINCT_IDS}
)
WHERE person_id IN
(
    SELECT id
    FROM (
        SELECT id, argMax(properties, person._timestamp) as properties, max(is_deleted) as is_deleted
        FROM person
        WHERE team_id = %(team_id)s
        GROUP BY id
        HAVING is_deleted = 0
    )
    WHERE {filters}
)
"""

GET_DISTINCT_IDS_BY_PERSON_ID_FILTER = """
SELECT distinct_id
FROM ({GET_TEAM_PERSON_DISTINCT_IDS})
WHERE {filters}
"""

GET_ACTORS_FROM_EVENT_QUERY = """
SELECT
    {id_field} AS actor_id,
    {actor_value_expression} AS actor_value
    {matching_events_select_statement}
FROM ({events_query})
GROUP BY actor_id
ORDER BY actor_value DESC, actor_id DESC /* Also sorting by ID for determinism */
{limit}
{offset}
"""

COMMENT_DISTINCT_ID_COLUMN_SQL = (
    lambda: "ALTER TABLE person_distinct_id COMMENT COLUMN distinct_id 'skip_0003_fill_person_distinct_id2'"
)


SELECT_PERSON_PROP_VALUES_SQL = """
SELECT
    value,
    count(value)
FROM (
    SELECT
        {property_field} as value
    FROM
        person
    WHERE
        team_id = %(team_id)s AND
        is_deleted = 0 AND
        {property_field} IS NOT NULL AND
        {property_field} != ''
    ORDER BY id DESC
    LIMIT 100000
)
GROUP BY value
ORDER BY count(value) DESC
LIMIT 20
"""

SELECT_PERSON_PROP_VALUES_SQL_WITH_FILTER = """
SELECT
    value,
    count(value)
FROM (
    SELECT
        {property_field} as value
    FROM
        person
    WHERE
        team_id = %(team_id)s AND
        is_deleted = 0 AND
        {property_field} ILIKE %(value)s
    ORDER BY id DESC
    LIMIT 100000
)
GROUP BY value
ORDER BY count(value) DESC
LIMIT 20
"""

GET_PERSON_COUNT_FOR_TEAM = "SELECT count() AS count FROM person WHERE team_id = %(team_id)s"
GET_PERSON_DISTINCT_ID2_COUNT_FOR_TEAM = "SELECT count() AS count FROM person_distinct_id2 WHERE team_id = %(team_id)s"


def CREATE_PERSON_DISTINCT_ID_OVERRIDES_DICTIONARY():
    """
    Create dictionary SQL for person_distinct_id_overrides.
    This must be a function to ensure CLICKHOUSE_DATABASE is evaluated at runtime,
    not at module import time (which causes issues in E2E tests where env vars aren't loaded yet).
    """
    return """
CREATE OR REPLACE DICTIONARY {database}.person_distinct_id_overrides_dict ON CLUSTER {cluster} (
    `team_id` Int64, -- team_id could be made hierarchical to save some space.
    `distinct_id` String,
    `person_id` UUID
)
PRIMARY KEY team_id, distinct_id
-- For our own sanity, we explicitly write out the group by query.
SOURCE(CLICKHOUSE(
    query 'SELECT team_id, distinct_id, argMax(person_id, version) AS person_id FROM {database}.person_distinct_id_overrides GROUP BY team_id, distinct_id'
))
LAYOUT(complex_key_hashed())
-- ClickHouse will choose a time uniformly within 1 to 5 hours to reload the dictionary (update if necessary to meet SLAs).
LIFETIME(MIN 3600 MAX 18000)
""".format(
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )
