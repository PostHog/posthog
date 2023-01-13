CREATE_ELEMENTS_CHAIN_DAILY_COUNTS_TABLE = """
CREATE TABLE elements_chain_counts_daily
(
    day            DateTime64(3, 'UTC'),
    team_id        int,
    elements_chain String,
    "$current_url" String,
    count          int
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMM(day) ORDER BY (team_id,day,"$current_url", elements_chain);
"""

CREATE_ELEMENTS_CHAIN_DAILY_COUNTS_MV = """
CREATE MATERIALIZED VIEW elements_chain_counts_daily_mv
TO elements_chain_counts_daily
AS SELECT
    toStartOfDay(timestamp) as day,
    team_id,
    elements_chain,
    replaceRegexpAll(JSONExtractRaw(properties, '$current_url'), '^"|"$', '') as "$current_url",
    count(*) as count
FROM events
WHERE event = '$autocapture'
AND elements_chain != ''
GROUP BY team_id, day, elements_chain, "$current_url";
"""

GET_ELEMENTS_FROM_MV = """
SELECT
    elements_chain, sum(count) as count
FROM elements_chain_counts_daily_mv
WHERE
    team_id = %(team_id)s
    AND day >= toStartOfDay(%(date_from)s, 'UTC')
    AND day <= %(date_to)s
    AND "$current_url" = %(current_url)s
GROUP BY elements_chain
ORDER BY count DESC
"""


GET_ELEMENTS = """
SELECT
    elements_chain, count(1) as count
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
