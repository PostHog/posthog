# Web analytics snapshot — 2026-05-19 12:44 UTC (run-1244Z)

Diff vs run-1212Z. Cluster recovered; three distinct slow-query incidents
captured.

## Cluster recovered (again)

`clusterAllReplicas` works. Window for this recovery: somewhere between
12:12 UTC (broken) and 12:44 UTC (this run, working). Total cluster blind
time today is now ~2h cumulative.

## Three new slow-query incidents identified

`q31_recent_outliers.tsv` — all queries >8s since 11:00 UTC.

### Incident A — team 204248: shape problem, not scan-size

| time     | tag                       | duration | read_rows | memory_mb | access      |
| -------- | ------------------------- | -------- | --------- | --------- | ----------- |
| 12:17:48 | `stats_table_main_query`  | **32439**| 909K      | 700       | personal_api_key |
| 12:17:49 | `web_overview_query`      | **33542**| 765K      | 684       | personal_api_key |

Two queries from team 204248 via personal API key, **fired one second
apart**, both ~32s, both reading well under 1M rows. **31-second queries
on a million rows is a query-shape problem**, not a scan size problem.
Lazy precomputation won't help here. Looks like complex filter pushdown
or join inefficiency. Worth pulling the HogQL via the `query_id`s.

### Incident B — team 112458: paired-tile dashboard, massive scans

| time     | tag                             | duration | read_rows | memory_mb |
| -------- | ------------------------------- | -------- | --------- | --------- |
| 12:43:12 | `web_overview_query`            | 13239    | 326M      | 11958     |
| 12:43:18 | `stats_table_path_bounce_query` | 20099    | **651M**  | **24078** |

UI traffic, fired 6 seconds apart. The **24 GB memory** path_bounce query
is the largest single allocation we've observed all day on this skill's
queries. Same pattern as team 10085 earlier — multiple tiles on the same
dashboard hitting the same time range concurrently. This is the canonical
lazy-precomp target.

### Incident C — team 125691: scheduled external_clicks polling, now slow

| time     | duration | read_rows | memory_mb |
| -------- | -------- | --------- | --------- |
| 11:45:22 | 10654    | 982K      | 717       |
| 12:05:22 | 8578     | 999K      | 713       |

Team 125691's "search app" personal API key (already known as a heavy
poller). Two slow `external_clicks_query` events **exactly 20 minutes
apart** — strong evidence of a 20-minute polling cadence. Reading ~1M
rows but taking 9–11s. Like team 204248, this is a shape problem on
modest row counts — different cause but worth investigating since this
team has been the dominant `external_clicks_query` consumer all day.

## Per-tag 6h cluster numbers

| Tag                                     | cnt   | p95 ms | p99 ms | max ms |
| --------------------------------------- | ----- | ------ | ------ | ------ |
| `stats_table_main_query`                | 6487  | 1378   | 2449   | **32439** |
| `web_overview_query`                    | 2429  | 1310   | 2453   | **33542** |
| `stats_table_frustration_metrics_query` | 2061  | 1263   | 2251   | 7809   |
| `stats_table_path_bounce_query`         | 1954  | 2436   | 4499   | **20099** |
| `web_vitals_path_breakdown_query`       | 437   | 729    | 1117   | 1614   |
| `web_goals_query`                       | 330   | 2356   | 3623   | 54960  |
| `stats_table_entry_bounce_query`        | 304   | 1299   | 2174   | 2620   |
| `external_clicks_query`                 | 116   | 2308   | **8274** | **10654** |
| `stats_table_path_bounce_and_avg_time_query` | 1 | 2778   | 2778   | 2778   |

`external_clicks_query` p99 leaped from 1533 → 8274 ms — driven entirely
by team 125691's two slow events (Incident C). Filter on
`access_method='browser'` (empty string) for UI-only numbers.

## Earlier outlier identified (was queued from cluster blind window)

`q29_outage_window_outliers.tsv` — for the 10:00–11:00 UTC window:

| time     | tag                             | duration | team_id | read_rows | memory_mb |
| -------- | ------------------------------- | -------- | ------- | --------- | --------- |
| 10:04:18 | `stats_table_path_bounce_query` | 12271    | 121302  | **430M**  | 5651      |

So team 121302 ran one heavy path_bounce query during the cluster blind
window. Massive scan (430M rows, 5.6 GB). Not the 18s outlier I was
chasing (that one came from before 10:00 UTC, was captured in
run-1108Z's max_ms numbers from an earlier sub-window of the 6h aggregate).

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate (cluster restored)
- `q29_outage_window_outliers.tsv` — earlier outlier (team 121302)
- `q31_recent_outliers.tsv` — three new incidents A/B/C since 11:00 UTC

## Watch list for next iteration

1. Whether team 204248's personal-API-key slow queries recur (could be a
   newly-deployed integration that's hitting a slow shape every poll).
2. Whether team 112458 dashboard refreshes again.
3. Whether team 125691's 20-min cadence holds — next expected slow
   external_clicks query around 12:25Z + 20m = 12:45Z, then 13:05Z.
4. Cluster outage recurrence.
