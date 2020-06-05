CREATE MATERIALIZED VIEW sessions_team_1 AS
SELECT *,
SUM(new_session) OVER (ORDER BY distinct_id, timestamp) AS global_session_id,
SUM(new_session) OVER (PARTITION BY distinct_id ORDER BY timestamp) AS user_session_id                   
FROM (SELECT distinct_id, event, timestamp, properties, 
        CASE WHEN EXTRACT('EPOCH' FROM (timestamp - previous_timestamp)) >= (60 * 30) OR previous_timestamp IS NULL THEN 1 ELSE 0 END AS new_session 
        FROM (SELECT "posthog_event"."id", "posthog_event"."team_id", "posthog_event"."event", "posthog_event"."distinct_id", "posthog_event"."properties", "posthog_event"."elements", "posthog_event"."timestamp", "posthog_event"."elements_hash", (SELECT U0."person_id" FROM "posthog_persondistinctid" U0 WHERE (U0."distinct_id" = "posthog_event"."distinct_id" AND U0."team_id" = 2) LIMIT 1) AS "person_id", LAG("posthog_event"."timestamp", 1) OVER (PARTITION BY "posthog_event"."distinct_id" ORDER BY "posthog_event"."timestamp" ASC) AS "previous_timestamp", LAG("posthog_event"."event", 1) OVER (PARTITION BY "posthog_event"."distinct_id" ORDER BY "posthog_event"."timestamp" ASC) AS "previous_event" FROM "posthog_event" WHERE "posthog_event"."team_id" = 2 ORDER BY "posthog_event"."timestamp" DESC) AS inner_sessions) AS outer_sessions;

CREATE MATERIALIZED VIEW sessions_feed_team_2 AS 
SELECT properties, start_time, length, sessions.distinct_id, event_count, events from
        (SELECT
            global_session_id,
            count(1) as event_count,
            MAX(distinct_id) as distinct_id,
            EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp))) AS length,
            MIN(timestamp) as start_time,
            array_agg(json_build_object('event', event, 'timestamp', timestamp, 'properties', properties) ORDER BY timestamp) as events
                FROM sessions_team_1 as count GROUP BY 1) as sessions
                LEFT OUTER JOIN posthog_persondistinctid ON posthog_persondistinctid.distinct_id = sessions.distinct_id
                LEFT OUTER JOIN posthog_person ON posthog_person.id = posthog_persondistinctid.person_id
                ORDER BY start_time DESC;