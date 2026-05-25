# Web analytics snapshot — 2026-05-19 12:12 UTC (run-1212Z)

Diff vs run-1140Z. Cluster outage continues; EU midday is calm.

## Cluster outage timeline (third confirmed window)

`clusterAllReplicas` failing again with the same replica URI. Updated
timeline:

- 10:00 → ~10:55 UTC: broken
- ~11:00 → ~11:08 UTC: working (resolved briefly in run-1108Z)
- 11:40 UTC: broken again (run-1140Z)
- 12:12 UTC: still broken (this run)

Cumulative blind time ~1h45 over a 2h12 window. This is an active
intermittent issue — not a one-shot recovery problem.

## EU midday signal from local replica: 1 slow query in 2 hours

`q30_local_slow_2h.tsv` — the only `>5s` web-analytics query visible to
this replica in the last 2 hours:

| team_id | tag                 | duration | read_rows | memory_mb | event_time |
| ------- | ------------------- | -------- | --------- | --------- | ---------- |
| 234917  | `web_goals_query`   | 6229     | 11.5M     | 3175      | 11:55:56   |

One isolated user-driven `web_goals_query`. Modest row count (11.5M),
modest memory (3.2 GB). Not part of any pattern — no neighboring slow
queries from the same team, no cluster of slow queries from other teams.

So through 2 hours of EU midday peak (10:12 → 12:12 UTC), the visible
replica saw exactly one slow web-analytics query. That's a healthy
signal, even accounting for the cluster blindness.

## Local 6h aggregate: stable

| Tag                                     | cnt | p95 ms | p99 ms |
| --------------------------------------- | --- | ------ | ------ |
| `stats_table_main_query`                | 325 | 1297   | 1917   |
| `web_overview_query`                    | 116 | 1407   | 2003   |
| `stats_table_frustration_metrics_query` | 110 | 1393   | 1893   |
| `stats_table_path_bounce_query`         | 108 | 2546   | 4759   |
| `web_vitals_path_breakdown_query`       | 29  | 597    | 754    |
| `web_goals_query`                       | 23  | 1903   | 2150   |
| `external_clicks_query`                 | 8   | 724    | 753    |
| `stats_table_entry_bounce_query`        | 6   | 1085   | 1095   |

Numbers stable since prior local 6h view. path_bounce p95 ticked up
slightly (1380 → 2546) — the 11:55 goals query and a few other p99-band
queries entered the window. Otherwise drift only.

## Still pending: identification of 22s + 18s outliers

Couldn't reach the cluster again this iteration. Those outliers' team_ids
remain unidentified pending stable cluster recovery.

## Files

- `q11c_local_only_6h.tsv` — local 6h aggregate
- `q30_local_slow_2h.tsv` — one slow goals query (the only one visible)

## Watch list for next iteration

1. Whether cluster recovers stably (current cumulative ~1h45 of blind time).
2. If yes, pull team_ids for outliers from the 10:00–11:00 UTC window.
3. Whether the singleton 6.2s goals query from team 234917 is a one-shot
   or the start of a pattern (e.g., team 234917 also dashboarding).
