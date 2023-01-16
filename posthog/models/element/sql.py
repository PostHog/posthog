"""
For sums and counts SummingMerge can hide the complexity needed for other aggregations

As this materialised view will only be used for counts, we can use the simpler insert/query mechanism that offers.
see GET_ELEMENTS_FROM_MV

there are only two queries

```
WHERE team_id = %(team_id)s
    AND day >= toStartOfDay(%(date_from)s, 'UTC')
    AND day <= %(date_to)s
    AND "$current_url" = %(current_url)s
```

and

```
WHERE team_id = %(team_id)s
    AND day >= toStartOfDay(%(date_from)s, 'UTC')
    AND day <= %(date_to)s
    AND "$current_url" = %(current_url)s
```

"""
from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplicationScheme, SummingMergeTree

SHARDED_ELEMENTS_CHAIN_DAILY_COUNTS_TABLE_ENGINE = lambda: SummingMergeTree(
    "sharded_elements_chain_counts_daily", replication_scheme=ReplicationScheme.SHARDED
)

ELEMENTS_CHAIN_DAILY_COUNTS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE sharded_elements_chain_counts_daily ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
    day            DateTime64(3, 'UTC'),
    team_id        int,
    elements_chain String,
    "$current_url" String,
    count          int
)
ENGINE = {SHARDED_ELEMENTS_CHAIN_DAILY_COUNTS_TABLE_ENGINE()}
PARTITION BY toYYYYMM(day) ORDER BY (team_id,day,"$current_url", elements_chain);
"""
)

DISTRIBUTED_ELEMENTS_CHAIN_DAILY_COUNTS_TABLE_SQL = (
    lambda: f"""
CREATE TABLE elements_chain_counts_daily ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
        day            DateTime64(3, 'UTC'),
    team_id        int,
    elements_chain String,
    "$current_url" String,
    count          int
)
ENGINE={Distributed(data_table="sharded_elements_chain_counts_daily", sharding_key="rand()")}
"""
)

ELEMENTS_CHAIN_DAILY_COUNTS_MV_SQL = (
    lambda: f"""
CREATE MATERIALIZED VIEW elements_chain_counts_daily_mv ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
TO {settings.CLICKHOUSE_DATABASE}.sharded_elements_chain_counts_daily
AS SELECT
    toStartOfDay(timestamp) as day,
    team_id,
    elements_chain,
    replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', '') as "$current_url",
    count(*) as count
FROM {settings.CLICKHOUSE_DATABASE}.sharded_events
WHERE event = '$autocapture'
AND elements_chain != ''
GROUP BY team_id, day, elements_chain, "$current_url";
"""
)

GET_ELEMENTS_FROM_MV = """
SELECT
    elements_chain, sum(count) as count
FROM elements_chain_counts_daily_mv
WHERE
    team_id = %(team_id)s
    AND day >= toStartOfDay(%(date_from)s, 'UTC')
    AND day <= %(date_to)s
    AND {current_url_query}
GROUP BY elements_chain
ORDER BY count DESC
"""

# get the number of days between now and the first event for a team
GET_NUMBER_OF_DAYS_IN_ELEMENTS_CHAIN_DAILY_COUNTS = """
SELECT date_diff('day', min(day), now()) as number_of_days
FROM elements_chain_counts_daily_mv
WHERE team_id = %(team_id)s
"""


GET_ELEMENTS = """
SELECT
    elements_chain, count(*) as count
FROM events
WHERE
    team_id = %(team_id)s AND
    event = '$autocapture' AND
    elements_chain != ''
    {date_from}
    {date_to}
    {query}
GROUP BY elements_chain
ORDER BY count DESC
LIMIT {limit}{conditional_offset};
"""

GET_VALUES = """
SELECT
    extract(elements_chain, %(regex)s) as value, count(1) as count
FROM (
      SELECT elements_chain
      FROM events
      WHERE team_id = %(team_id)s
        AND event = '$autocapture'
        AND elements_chain != ''
        AND match(elements_chain, %(filter_regex)s)
        LIMIT 100000
)
GROUP BY value
ORDER BY count desc
LIMIT 100;
"""
