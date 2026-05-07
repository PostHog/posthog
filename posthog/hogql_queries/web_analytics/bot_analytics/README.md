# Bot Analytics precomputation

Precomputation backing for the **Bots** tab on Web Analytics.
Uses the lazy-computation framework
(`products/analytics_platform/backend/lazy_computation/`) to materialise
hourly request counts per breakdown, so the most common 7 / 14 / 30 day
queries don't have to scan raw events on every refresh.

## What gets precomputed

The bots tab counts events that match
`$virt_is_bot = true AND $virt_bot_name != ''`,
and is restricted to the three telemetry events the SDK marks as bot-eligible:
`$pageview`, `$screen`, `$http_log`.

The trends tile breaks down by one of four dimensions, each treated as a
separate query hash:

- `$virt_bot_name` — Crawler
- `$virt_traffic_category` — Category
- `$host` — Host
- `$pathname` — Path

For each breakdown we lazily build daily jobs in `preaggregation_results` of
the shape:

```
SELECT
  toStartOfHour(timestamp)            AS time_window_start,
  [coalesce(toString(<breakdown>), '')] AS breakdown_value,
  uniqExactState(uuid)                AS uniq_exact_state
FROM events
WHERE $virt_is_bot = true
  AND $virt_bot_name != ''
  AND event IN ('$pageview', '$screen', '$http_log')
  AND timestamp >= {time_window_min}
  AND timestamp < {time_window_max}
GROUP BY time_window_start, breakdown_value
```

`uuid` is unique per event, so `uniqExactMerge(uniq_exact_state)` returns the
exact request count when read back. Hourly buckets are the finest grain we
support; consumers re-bucket to day / week / month at read time.

## TTL schedule

```
"0d":      15 min          # current day, refreshed often
"1d":      1 hour          # yesterday
"7d":      1 day           # last week
"default": 7 days          # older windows are effectively frozen
```

Late-arriving bot events are negligible at our scale, so the long default
TTL is safe.

## Using it

```python
from datetime import datetime, UTC, timedelta
from posthog.hogql_queries.web_analytics.bot_analytics import (
    BotTrendsBreakdown,
    bot_trends_select_query,
    ensure_bot_analytics_precomputed,
)

date_to = datetime.now(UTC)
date_from = date_to - timedelta(days=30)

result = ensure_bot_analytics_precomputed(
    team=team,
    breakdown=BotTrendsBreakdown.CRAWLER,
    date_from=date_from,
    date_to=date_to,
)

select = bot_trends_select_query(
    job_ids=[str(j) for j in result.job_ids],
    date_from=date_from,
    date_to=date_to,
    interval="day",
)
```

The returned `SelectQuery` has columns `(bucket, breakdown_value, requests)`.
By default it returns the top 10 breakdowns ranked by total requests; pass
`limit_breakdowns=None` to disable.

## Warming

`posthog/tasks/web_analytics_bot_warming.py` defines two Celery tasks:

- `schedule_bot_analytics_warming_task` — fans out per-team, hourly at
  minute 45 (registered in `posthog/tasks/scheduled.py`)
- `warm_bot_analytics_for_team_task(team_id)` — runs all four breakdowns
  for the trailing 30 days for one team

The task targets the same `cache-warming` opt-in cohort that the regular
insight warmer uses. Warming the trailing 30-day window covers the 7 / 14 /
30 day presets the bot tab exposes.

## Wiring this into the runtime path

The frontend currently sends a `TrendsQuery` for the bot trends tile (see
`frontend/src/scenes/web-analytics/botAnalyticsLogic.ts`). To complete the
fast path end-to-end, two follow-ups are needed:

1. **Detect-and-rewrite in `TrendsQueryRunner`.** When the query matches
   the bot signature (`$virt_is_bot=true` + a bot-events series + one of
   the four breakdowns), call `ensure_bot_analytics_precomputed` and feed
   the result into `bot_trends_select_query` instead of scanning raw
   events. The shape of `TrendsQueryResponse` and the breakdown ordering
   will need a dedicated adapter.
2. **Or:** introduce a dedicated `WebBotTrendsQuery` schema and runner
   (mirroring `WebTrendsQueryRunner`), then update
   `botAnalyticsLogic.ts` to emit it. Schema changes flow through
   `hogli build:schema`.

The library shipped in this directory is the prerequisite for either
choice. Until one of them is wired up, warming populates the
`preaggregation_results` table but readers won't see a speedup.

## See also

- `products/analytics_platform/backend/lazy_computation/README.md` —
  underlying framework, concurrency model, stale-job recovery.
- `posthog/clickhouse/preaggregation/sql.py` — schema of
  `preaggregation_results`.
- `posthog/hogql_queries/experiments/experiment_exposures_query_runner.py`
  — reference for using `ensure_precomputed` from a query runner.
