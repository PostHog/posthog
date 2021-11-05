from ee.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

from .clickhouse import (
    COLLAPSING_MERGE_TREE,
    KAFKA_COLUMNS,
    REPLACING_MERGE_TREE,
    STORAGE_POLICY,
    kafka_engine,
    table_engine,
)

TRUNCATE_PERSON_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS person ON CLUSTER {CLICKHOUSE_CLUSTER}"

DROP_PERSON_TABLE_SQL = f"DROP TABLE IF EXISTS person ON CLUSTER {CLICKHOUSE_CLUSTER}"

TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS person_distinct_id ON CLUSTER {CLICKHOUSE_CLUSTER}"

PERSONS_TABLE = "person"

PERSONS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER {cluster}
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Boolean,
    is_deleted Boolean DEFAULT 0
    {extra_fields}
) ENGINE = {engine}
"""

PERSONS_TABLE_SQL = (
    PERSONS_TABLE_BASE_SQL
    + """Order By (team_id, id)
{storage_policy}
"""
).format(
    table_name=PERSONS_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=table_engine(PERSONS_TABLE, "_timestamp", REPLACING_MERGE_TREE),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY,
)

KAFKA_PERSONS_TABLE_SQL = PERSONS_TABLE_BASE_SQL.format(
    table_name="kafka_" + PERSONS_TABLE, cluster=CLICKHOUSE_CLUSTER, engine=kafka_engine(KAFKA_PERSON), extra_fields="",
)

# You must include the database here because of a bug in clickhouse
# related to https://github.com/ClickHouse/ClickHouse/issues/10471
PERSONS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv ON CLUSTER {cluster}
TO {database}.{table_name}
AS SELECT
id,
created_at,
team_id,
properties,
is_identified,
is_deleted,
_timestamp,
_offset
FROM {database}.kafka_{table_name}
""".format(
    table_name=PERSONS_TABLE, cluster=CLICKHOUSE_CLUSTER, database=CLICKHOUSE_DATABASE,
)

GET_LATEST_PERSON_SQL = """
SELECT * FROM person JOIN (
    SELECT id, max(_timestamp) as _timestamp, max(is_deleted) as is_deleted
    FROM person
    WHERE team_id = %(team_id)s
    GROUP BY id
) as person_max ON person.id = person_max.id AND person._timestamp = person_max._timestamp
WHERE team_id = %(team_id)s
  AND person_max.is_deleted = 0
  {query}
"""

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

GET_LATEST_PERSON_ID_SQL = """
(select id from (
    {latest_person_sql}
))
""".format(
    latest_person_sql=GET_LATEST_PERSON_SQL
)

PERSONS_DISTINCT_ID_TABLE = "person_distinct_id"

PERSONS_DISTINCT_ID_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER {cluster}
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Int8 DEFAULT 1,
    is_deleted Int8 ALIAS if(_sign==-1, 1, 0)
    {extra_fields}
) ENGINE = {engine}
"""

PERSONS_DISTINCT_ID_TABLE_SQL = (
    PERSONS_DISTINCT_ID_TABLE_BASE_SQL
    + """Order By (team_id, distinct_id, person_id)
{storage_policy}
"""
).format(
    table_name=PERSONS_DISTINCT_ID_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=table_engine(PERSONS_DISTINCT_ID_TABLE, "_sign", COLLAPSING_MERGE_TREE),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY,
)

# :KLUDGE: We default is_deleted to 0 for backwards compatibility for when we drop `is_deleted` from message schema.
#    Can't make DEFAULT if(_sign==-1, 1, 0) because Cyclic aliases error.
KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL = """
CREATE TABLE {table_name} ON CLUSTER {cluster}
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
CREATE MATERIALIZED VIEW {table_name}_mv ON CLUSTER {cluster}
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
# Static Cohort
#

PERSON_STATIC_COHORT_TABLE = "person_static_cohort"
PERSON_STATIC_COHORT_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER {cluster}
(
    id UUID,
    person_id UUID,
    cohort_id Int64,
    team_id Int64
    {extra_fields}
) ENGINE = {engine}
"""

PERSON_STATIC_COHORT_TABLE_SQL = (
    PERSON_STATIC_COHORT_BASE_SQL
    + """Order By (team_id, cohort_id, person_id, id)
{storage_policy}
"""
).format(
    table_name=PERSON_STATIC_COHORT_TABLE,
    cluster=CLICKHOUSE_CLUSTER,
    engine=table_engine(PERSON_STATIC_COHORT_TABLE, "_timestamp", REPLACING_MERGE_TREE),
    storage_policy=STORAGE_POLICY,
    extra_fields=KAFKA_COLUMNS,
)

TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL = (
    f"TRUNCATE TABLE IF EXISTS {PERSON_STATIC_COHORT_TABLE} ON CLUSTER {CLICKHOUSE_CLUSTER}"
)

INSERT_PERSON_STATIC_COHORT = (
    f"INSERT INTO {PERSON_STATIC_COHORT_TABLE} (id, person_id, cohort_id, team_id, _timestamp) VALUES"
)

#
# Other queries
#

GET_PERSON_IDS_BY_FILTER = """
SELECT DISTINCT p.id
FROM ({latest_person_sql}) AS p
INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS pdi ON p.id = pdi.person_id
WHERE team_id = %(team_id)s
  {distinct_query}
""".format(
    latest_person_sql=GET_LATEST_PERSON_SQL,
    distinct_query="{distinct_query}",
    GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
)

INSERT_PERSON_SQL = """
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted) SELECT %(id)s, %(created_at)s, %(team_id)s, %(properties)s, %(is_identified)s, %(_timestamp)s, 0, 0
"""

INSERT_PERSON_DISTINCT_ID = """
INSERT INTO person_distinct_id SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, %(_sign)s, now(), 0 VALUES
"""

DELETE_PERSON_BY_ID = """
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted) SELECT %(id)s, %(created_at)s, %(team_id)s, %(properties)s, %(is_identified)s, %(_timestamp)s, 0, 1
"""

DELETE_PERSON_EVENTS_BY_ID = """
ALTER TABLE events DELETE
WHERE distinct_id IN (
    SELECT distinct_id FROM person_distinct_id WHERE person_id=%(id)s AND team_id = %(team_id)s
)
AND team_id = %(team_id)s
"""

INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID = """
INSERT INTO {cohort_table} SELECT generateUUIDv4(), id, %(cohort_id)s, %(team_id)s, %(_timestamp)s, 0 FROM (
    SELECT person_id as id FROM ({query})
)
"""

PEOPLE_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM (
    {latest_person_sql}
) as person INNER JOIN (
    SELECT person_id, distinct_id FROM ({GET_TEAM_PERSON_DISTINCT_IDS}) WHERE person_id IN ({content_sql})
) as pdi ON person.id = pdi.person_id
GROUP BY id, created_at, team_id, properties, is_identified
LIMIT 100 OFFSET %(offset)s
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
    WHERE 1 = 1 {filters}
)
""".format(
    filters="{filters}", GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
)

GET_DISTINCT_IDS_BY_PERSON_ID_FILTER = """
SELECT distinct_id
FROM ({GET_TEAM_PERSON_DISTINCT_IDS})
WHERE {filters}
""".format(
    filters="{filters}", GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
)

GET_PERSON_PROPERTIES_COUNT = """
SELECT tupleElement(keysAndValues, 1) as key, count(*) as count
FROM person
ARRAY JOIN JSONExtractKeysAndValuesRaw(properties) as keysAndValues
WHERE team_id = %(team_id)s
GROUP BY tupleElement(keysAndValues, 1)
ORDER BY count DESC, key ASC
"""

GET_PERSONS_FROM_EVENT_QUERY = """
SELECT
    person_id,
    created_at,
    team_id,
    person_props,
    is_identified,
    arrayReduce('groupUniqArray', groupArray(distinct_id)) AS distinct_ids
FROM ({events_query})
GROUP BY
    person_id,
    created_at,
    team_id,
    person_props,
    is_identified
LIMIT %(limit)s
OFFSET %(offset)s
"""
