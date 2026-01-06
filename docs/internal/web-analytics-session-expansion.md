# Web Analytics Session Expansion

## Overview

Web Analytics uses session-based filtering to aggregate metrics. The "session expansion" setting controls how sessions that span date boundaries are handled.

## How Queries Work

### Inner Query (Event Filtering)

```sql
SELECT
    any(person_id) AS filtered_person_id,
    session.session_id AS session_id,
    min(session.$start_timestamp) AS start_timestamp  -- or min(events.timestamp) when expansion is OFF
FROM events
WHERE events.timestamp >= date_from AND events.timestamp <= date_to
GROUP BY session_id
```

Events are filtered by their timestamp within the selected date range.

### Outer Query (Period Aggregation)

```sql
SELECT
    uniqIf(person_id, start_timestamp >= date_from AND start_timestamp <= date_to) AS visitors
FROM inner_query
```

Metrics are aggregated based on when the **session started**, not when events occurred.

## The Mismatch Problem

A session might:

- Start at 11:30 PM on Dec 31
- Have pageviews at 12:05 AM on Jan 1

If you query "Jan 1 - Jan 7":

- The events from Jan 1 are included in the WHERE clause
- But the session started on Dec 31, so `start_timestamp < date_from`
- The visitor is **not counted** in the aggregation

## Session Expansion Setting

### Enabled (Default)

- `start_timestamp` = `min(session.$start_timestamp)` (session start time)
- Sessions starting before the date range are included if they have events within it
- This is the traditional Web Analytics behavior

### Disabled

- `start_timestamp` = `min(events.timestamp)` (first event timestamp within range)
- Only events within the date range are considered for the timestamp
- Totals will match Product Analytics trends queries
- Session-based metrics (bounce rate, session duration) use partial session data

## Implementation Details

The `start_timestamp_expr` property in `WebAnalyticsQueryRunner` controls this behavior:

```python
@cached_property
def start_timestamp_expr(self) -> str:
    if self.session_expansion_enabled:
        return "min(session.$start_timestamp)"
    else:
        return "min(events.timestamp)"
```

This expression is used in:

- `web_overview.py`: Inner select query
- `stats_table.py`: All query template placeholders (`PATH_BOUNCE_QUERY`, `PATH_SCROLL_BOUNCE_QUERY`, `PATH_BOUNCE_AND_AVG_TIME_QUERY`, `FRUSTRATION_METRICS_INNER_QUERY`, `MAIN_INNER_QUERY`)

## Related Files

- `posthog/hogql_queries/web_analytics/web_analytics_query_runner.py`: Base runner with `start_timestamp_expr`
- `posthog/hogql_queries/web_analytics/web_overview.py`: Overview query implementation
- `posthog/hogql_queries/web_analytics/stats_table.py`: Stats table query implementation
- `posthog/hogql_queries/web_analytics/query_constants/stats_table_queries.py`: Query templates
- `posthog/models/team/team.py`: `web_analytics_session_expansion_enabled` setting
- `frontend/src/scenes/settings/environment/WebAnalyticsEventSettings.tsx`: Settings UI
