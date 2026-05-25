# Web analytics snapshot — 2026-05-19 10:03 UTC (run-1003Z)

Diff vs run-0931Z. **Partial outage caveat below.**

## Caveat: `clusterAllReplicas(posthog, system, query_log)` is failing

```
Code: 279. DB::NetException: ALL_CONNECTION_TRIES_FAILED
server ClickHouseNode [uri=…prod-us-iad-ch-online.internal.ec2…]
```

Three consecutive attempts to query `clusterAllReplicas(posthog, system, query_log)`
returned this. At least one replica in the ONLINE cluster is unreachable from
Metabase's perspective. Single-node `FROM system.query_log` works — but it
only sees queries that ran on one specific replica, which is roughly 5–10%
of cluster-wide traffic.

**All numbers in this iteration are from local-replica data, not the full
cluster.** The shapes and relative ratios are still informative; absolute
counts are not.

If anyone runs this skill's queries right now, they'll hit the same error.
Fallback recipe: replace `clusterAllReplicas(posthog, system, query_log)`
with `system.query_log` for the duration of the outage.

## Headline: team 2 and team 10085 heavy activity has stopped (apparently)

`q26_heavy_teams_1h_local.tsv` for the last 1h:

| team_id | cnt | over_5s | avg ms | max ms | max read_rows | total_memory |
| ------- | --- | ------- | ------ | ------ | ------------- | ------------ |
| 2       | 0   | —       | —      | —      | —             | —            |
| 10085   | 2   | 0       | 184    | 184    | 297K          | 0.0 GB       |

Team 2 has no rows at all in the last hour — the 09:07–09:08 monster
queries (1.25B rows / 54s) appear to have been one-shot.

Team 10085 dropped from 30 heavy queries / 50 min to 2 light queries
(184ms each, 297K rows) in the last hour. Either:

1. The user finished their session / closed the dashboard.
2. They narrowed the filter / shortened the date range so the queries are
   now small.
3. Their queries are landing on the unreachable replica and we're missing
   them. The cluster outage makes this ambiguous.

Either way, the visible part of the system is now calm.

## Per-tag 6h local view (`q11c_local_only_6h.tsv`)

| Tag                                     | cnt | avg ms | p95 ms | p99 ms |
| --------------------------------------- | --- | ------ | ------ | ------ |
| `stats_table_main_query`                | 290 | 656    | 1254   | 2535   |
| `web_overview_query`                    | 114 | 639    | 1090   | 2629   |
| `stats_table_frustration_metrics_query` | 93  | 688    | 1809   | 3695   |
| `stats_table_path_bounce_query`         | 92  | 1173   | 2635   | 3614   |
| `web_goals_query`                       | 20  | 921    | 2001   | 2417   |
| `stats_table_entry_bounce_query`        | 13  | 556    | 701    | 726    |
| `web_vitals_path_breakdown_query`       | 12  | 209    | 267    | 269    |
| `external_clicks_query`                 | 3   | 670    | 1095   | 1155   |

This single replica is showing healthy steady-state numbers — p95s for
main_query, overview, goals, vitals all sit in the 200–2700 ms band. The
worst tag, path_bounce, sits at 2.6s p95 on this slice (consistent with
prior cluster aggregates).

Crucially: no `stats_table_query` (legacy) rows in the local 6h view. Either
the legacy emitters have fully drained off this replica, or the local
replica never saw recent legacy traffic. Hopefully convergence; the
cluster outage prevents confirmation.

## Files

- `q11c_local_only_6h.tsv` — per-tag 6h aggregate from single replica
- `q26_heavy_teams_1h_local.tsv` — team 2 + team 10085 last hour from single replica

(`q11b_all_web_tags_6h.tsv` was not generated — cluster query failed.)

## Watch list for next iteration

1. Whether `clusterAllReplicas` is back. If yes, re-run the full set and
   confirm legacy `stats_table_query` truly hit zero.
2. Whether team 2 or team 10085 resume heavy activity.
3. Once cluster is healthy, run the full path_bounce timeline to see if
   the morning EU peak (currently in progress, 09:00–11:00Z) produces a
   user-driven slow cluster.
