-- Why does the sessionless entry page disagree with the sessions table? Per session, compare the first
-- pageview's $pathname with the path of the first pageview's $current_url (what sessions v2/v3 store).
SELECT
    count() AS sessions,
    countIf(entry_pathname != entry_url_path) AS differ,
    round(100 * countIf(entry_pathname != entry_url_path) / count(), 2) AS differ_pct,
    countIf(entry_pathname = '/' AND entry_url_path != '/') AS pathname_root_but_url_not,
    countIf(entry_pathname IS NULL) AS no_pathname
FROM (
    SELECT
        events.properties.`$session_id` AS s,
        argMin(nullIf(toString(events.properties.`$pathname`), ''), events.timestamp) AS entry_pathname,
        path(argMin(toString(events.properties.`$current_url`), events.timestamp)) AS entry_url_path
    FROM events_json AS events
    WHERE equals(events.team_id, TEAM_ID) AND in(events.event, ['$pageview', '$screen'])
      AND isNotNull(toUUIDOrNull(events.properties.`$session_id`))
      AND events.timestamp >= toDateTime('DATE_TO 00:00:00', 'UTC') AND events.timestamp <= toDateTime('DATE_TO 23:59:59', 'UTC')
    GROUP BY s
)
SETTINGS max_execution_time = 270
