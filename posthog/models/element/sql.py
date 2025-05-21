GET_ELEMENTS = """
SELECT
    elements_chain, count() / %(sampling_factor)s as count, event as event_type
FROM events
SAMPLE %(sampling_factor)s
WHERE
    team_id = %(team_id)s AND
    event in %(filter_event_types)s AND
    elements_chain != ''
    {date_from}
    {date_to}
    {query}
GROUP BY elements_chain, event
ORDER BY count DESC
LIMIT {limit} OFFSET {offset};
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
