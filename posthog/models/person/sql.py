from posthog.clickhouse.kafka_engine import (
    COPY_ROWS_BETWEEN_TEAMS_BASE_SQL,
    KAFKA_COLUMNS,
    STORAGE_POLICY,
    kafka_engine,
)
from posthog.clickhouse.table_engines import CollapsingMergeTree, ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID, KAFKA_PERSON_UNIQUE_ID
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

TRUNCATE_PERSON_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS person ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

DROP_PERSON_TABLE_SQL = f"DROP TABLE IF EXISTS person ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS person_distinct_id ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL = (
    f"TRUNCATE TABLE IF EXISTS person_distinct_id2 ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)

PERSONS_TABLE = "person"

PERSONS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8 DEFAULT 0,
    version UInt64
    {extra_fields}
) ENGINE = {engine}
"""

PERSONS_TABLE_ENGINE = lambda: ReplacingMergeTree(PERSONS_TABLE, ver="version")
PERSONS_TABLE_SQL = lambda: (
    PERSONS_TABLE_BASE_SQL
    + """Order By (team_id, id)
{storage_policy}
"""
).format(
    table_name=PERSONS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=PERSONS_TABLE_ENGINE(),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY(),
)

KAFKA_PERSONS_TABLE_SQL = lambda: PERSONS_TABLE_BASE_SQL.format(
    table_name="kafka_" + PERSONS_TABLE, cluster=CLICKHOUSE_CLUSTER, engine=kafka_engine(KAFKA_PERSON), extra_fields="",
)

# You must include the database here because of a bug in clickhouse
# related to https://github.com/ClickHouse/ClickHouse/issues/10471
PERSONS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv ON CLUSTER '{cluster}'
TO {database}.{table_name}
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
FROM {database}.kafka_{table_name}
""".format(
    table_name=PERSONS_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE,
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
""".format(
    latest_person_sql=GET_LATEST_PERSON_SQL
)

#
# person_distinct_id table - use this still in queries, but this will eventually get removed.
#


PERSONS_DISTINCT_ID_TABLE = "person_distinct_id"

PERSONS_DISTINCT_ID_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Int8 DEFAULT 1,
    is_deleted Int8 ALIAS if(_sign==-1, 1, 0)
    {extra_fields}
) ENGINE = {engine}
"""

PERSONS_DISTINCT_ID_TABLE_SQL = lambda: (
    PERSONS_DISTINCT_ID_TABLE_BASE_SQL
    + """Order By (team_id, distinct_id, person_id)
{storage_policy}
"""
).format(
    table_name=PERSONS_DISTINCT_ID_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=CollapsingMergeTree(PERSONS_DISTINCT_ID_TABLE, ver="_sign"),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY(),
)

# :KLUDGE: We default is_deleted to 0 for backwards compatibility for when we drop `is_deleted` from message schema.
#    Can't make DEFAULT if(_sign==-1, 1, 0) because Cyclic aliases error.
KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL = lambda: """
CREATE TABLE {table_name} ON CLUSTER '{cluster}'
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Nullable(Int8),
    is_deleted Nullable(Int8)
) ENGINE = {engine}
""".format(
    table_name="kafka_" + PERSONS_DISTINCT_ID_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=kafka_engine(KAFKA_PERSON_UNIQUE_ID),
)

# You must include the database here because of a bug in clickhouse
# related to https://github.com/ClickHouse/ClickHouse/issues/10471
PERSONS_DISTINCT_ID_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv ON CLUSTER '{cluster}'
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
    table_name=PERSONS_DISTINCT_ID_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE,
)

#
# person_distinct_ids2 - new table!
#

PERSON_DISTINCT_ID2_TABLE = "person_distinct_id2"

PERSON_DISTINCT_ID2_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64 DEFAULT 1
    {extra_fields}
) ENGINE = {engine}
"""

PERSON_DISTINCT_ID2_TABLE_ENGINE = lambda: ReplacingMergeTree(PERSON_DISTINCT_ID2_TABLE, ver="version")
PERSON_DISTINCT_ID2_TABLE_SQL = lambda: (
    PERSON_DISTINCT_ID2_TABLE_BASE_SQL
    + """
    ORDER BY (team_id, distinct_id)
    SETTINGS index_granularity = 512
    """
).format(
    table_name=PERSON_DISTINCT_ID2_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=PERSON_DISTINCT_ID2_TABLE_ENGINE(),
    extra_fields=KAFKA_COLUMNS + "\n, _partition UInt64",
)

KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL = lambda: PERSON_DISTINCT_ID2_TABLE_BASE_SQL.format(
    table_name="kafka_" + PERSON_DISTINCT_ID2_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=kafka_engine(KAFKA_PERSON_DISTINCT_ID),
    extra_fields="",
)

# You must include the database here because of a bug in clickhouse
# related to https://github.com/ClickHouse/ClickHouse/issues/10471
PERSON_DISTINCT_ID2_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv ON CLUSTER '{cluster}'
TO {database}.{table_name}
AS SELECT
team_id,
distinct_id,
person_id,
is_deleted,
version,
_timestamp,
_offset,
_partition
FROM {database}.kafka_{table_name}
""".format(
    table_name=PERSON_DISTINCT_ID2_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE,
)

#
# Static Cohort
#

PERSON_STATIC_COHORT_TABLE = "person_static_cohort"
PERSON_STATIC_COHORT_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    id UUID,
    person_id UUID,
    cohort_id Int64,
    team_id Int64
    {extra_fields}
) ENGINE = {engine}
"""

PERSON_STATIC_COHORT_TABLE_ENGINE = lambda: ReplacingMergeTree(PERSON_STATIC_COHORT_TABLE, ver="_timestamp")
PERSON_STATIC_COHORT_TABLE_SQL = lambda: (
    PERSON_STATIC_COHORT_BASE_SQL
    + """Order By (team_id, cohort_id, person_id, id)
{storage_policy}
"""
).format(
    table_name=PERSON_STATIC_COHORT_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=PERSON_STATIC_COHORT_TABLE_ENGINE(),
    storage_policy=STORAGE_POLICY(),
    extra_fields=KAFKA_COLUMNS,
)

TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL = (
    f"TRUNCATE TABLE IF EXISTS {PERSON_STATIC_COHORT_TABLE} ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
)

INSERT_PERSON_STATIC_COHORT = (
    f"INSERT INTO {PERSON_STATIC_COHORT_TABLE} (id, person_id, cohort_id, team_id, _timestamp) VALUES"
)

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

SELECT_PERSONS_OF_TEAM = """SELECT * FROM {table_name} WHERE team_id = %(source_team_id)s""".format(
    table_name=PERSONS_TABLE,
)

SELECT_PERSON_DISTINCT_ID2S_OF_TEAM = """SELECT * FROM {table_name} WHERE team_id = %(source_team_id)s""".format(
    table_name=PERSON_DISTINCT_ID2_TABLE,
)

#
# Other queries
#

GET_TEAM_PERSON_DISTINCT_IDS = """
SELECT distinct_id, argMax(person_id, _timestamp) as person_id
FROM (
    SELECT distinct_id, person_id, max(_timestamp) as _timestamp
    FROM person_distinct_id
    WHERE team_id = %(team_id)s
    GROUP BY person_id, distinct_id, team_id
    HAVING max(is_deleted) = 0
)
GROUP BY distinct_id
"""

# Query to query distinct ids using the new table, will be used if 0003_fill_person_distinct_id2 migration is complete
GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE = """
SELECT distinct_id, argMax(person_id, version) as person_id
FROM person_distinct_id2
WHERE team_id = %(team_id)s
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
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version) SELECT %(id)s, %(created_at)s, %(team_id)s, %(properties)s, %(is_identified)s, %(_timestamp)s, 0, 0, %(version)s
"""

INSERT_PERSON_BULK_SQL = """
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted, version) VALUES
"""

INSERT_PERSON_DISTINCT_ID = """
INSERT INTO person_distinct_id SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, %(_sign)s, now(), 0 VALUES
"""

INSERT_PERSON_DISTINCT_ID2 = """
INSERT INTO person_distinct_id2 (distinct_id, person_id, team_id, is_deleted, version, _timestamp, _offset, _partition) SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, 0, %(version)s, now(), 0, 0 VALUES
"""

BULK_INSERT_PERSON_DISTINCT_ID2 = """
INSERT INTO person_distinct_id2 (distinct_id, person_id, team_id, is_deleted, version, _timestamp, _offset, _partition) VALUES
"""

DELETE_PERSON_BY_ID = """
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, version, _offset, is_deleted) SELECT %(id)s, %(created_at)s, %(team_id)s, %(properties)s, %(is_identified)s, %(_timestamp)s, %(version)s, 0, 1
"""


INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID = """
INSERT INTO {cohort_table} SELECT generateUUIDv4(), actor_id, %(cohort_id)s, %(team_id)s, %(_timestamp)s, 0 FROM (
    SELECT actor_id FROM ({query})
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

GET_PERSON_PROPERTIES_COUNT = """
SELECT tupleElement(keysAndValues, 1) as key, count(*) as count
FROM person
ARRAY JOIN JSONExtractKeysAndValuesRaw(properties) as keysAndValues
WHERE team_id = %(team_id)s
GROUP BY tupleElement(keysAndValues, 1)
ORDER BY count DESC, key ASC
"""

GET_ACTORS_FROM_EVENT_QUERY = """
SELECT
    {id_field} AS actor_id
    {matching_events_select_statement}
FROM ({events_query})
GROUP BY actor_id
{limit}
{offset}
"""

COMMENT_DISTINCT_ID_COLUMN_SQL = (
    lambda: f"ALTER TABLE person_distinct_id ON CLUSTER '{CLICKHOUSE_CLUSTER}' COMMENT COLUMN distinct_id 'skip_0003_fill_person_distinct_id2'"
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
