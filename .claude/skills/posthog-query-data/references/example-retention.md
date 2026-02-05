# Retention (unique users, $ai_trace -> $ai_trace in the next 12 weeks, recurring)

```sql
SELECT
    actor_activity.start_interval_index AS start_event_matching_interval,
    actor_activity.intervals_from_base AS intervals_from_base,
    COUNT(DISTINCT actor_activity.actor_id) AS count
FROM
    (SELECT
        events.person_id AS actor_id,
        arraySort(groupUniqArrayIf(toStartOfWeek(events.timestamp, 3), and(and(equals(events.event, '$ai_trace'), in(properties.$ai_span_name, tuple('LangGraph', 'LangGraphUpdateState'))), and(greaterOrEquals(events.timestamp, toStartOfWeek(assumeNotNull(toDateTime('2025-11-03 00:00:00')))), less(events.timestamp, toDateTime('2026-02-02 00:00:00.000000')))))) AS start_event_timestamps,
        arrayMap(x -> plus(toStartOfWeek(assumeNotNull(toDateTime('2025-11-03 00:00:00'))), toIntervalWeek(x)), range(0, 13)) AS date_range,
        arraySort(groupUniqArrayIf(toStartOfWeek(events.timestamp, 3), and(and(equals(events.event, '$ai_trace'), in(properties.$ai_span_name, tuple('LangGraphUpdateState', 'LangGraph'))), and(greaterOrEquals(events.timestamp, toStartOfWeek(assumeNotNull(toDateTime('2025-11-03 00:00:00')))), less(events.timestamp, toDateTime('2026-02-02 00:00:00.000000')))))) AS return_event_timestamps,
        arrayJoin(arrayFilter(x -> greater(x, -1), arrayMap((interval_index, interval_date) -> if(has(start_event_timestamps, interval_date), minus(interval_index, 1), -1), arrayEnumerate(date_range), date_range))) AS start_interval_index,
        arrayJoin(arrayConcat(if(has(start_event_timestamps, date_range[plus(start_interval_index, 1)]), [0], []), arrayFilter(x -> greater(x, 0), arrayMap(_timestamp -> minus(indexOf(arraySlice(date_range, plus(start_interval_index, 1), 13), _timestamp), 1), return_event_timestamps)))) AS intervals_from_base
    FROM
        events
    WHERE
        and(1, and(greaterOrEquals(events.timestamp, toStartOfWeek(assumeNotNull(toDateTime('2025-11-03 00:00:00')))), less(events.timestamp, toDateTime('2026-02-02 00:00:00.000000'))), in(event, tuple('$ai_trace')), or(and(equals(events.event, '$ai_trace'), in(properties.$ai_span_name, tuple('LangGraph', 'LangGraphUpdateState'))), and(equals(events.event, '$ai_trace'), in(properties.$ai_span_name, tuple('LangGraphUpdateState', 'LangGraph')))))
    GROUP BY
        actor_id) AS actor_activity
GROUP BY
    start_event_matching_interval,
    intervals_from_base
ORDER BY
    start_event_matching_interval ASC,
    intervals_from_base ASC
```
