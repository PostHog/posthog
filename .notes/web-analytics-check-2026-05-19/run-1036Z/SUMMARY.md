# Web analytics snapshot — 2026-05-19 10:36 UTC (run-1036Z)

Diff vs run-1003Z. Cluster outage continues.

## Cluster outage still active (~35 min and counting)

`clusterAllReplicas(posthog, system, query_log)` still failing on **both**
clusters now:

- ONLINE (db 143): `ALL_CONNECTION_TRIES_FAILED` (CH 25.12.8.9)
- OFFLINE (db 142): `ALL_CONNECTION_TRIES_FAILED` (CH 26.3.10.60)

Same error shape, but the failing replica is different on each cluster.
This is independent of the ONLINE outage from the prior iteration — both
clusters have at least one unreachable replica simultaneously, which
suggests a Metabase-side issue (e.g., the credentials/cert it uses to
talk to ClickHouse, or a network-level problem from the Metabase host)
rather than two unrelated cluster events.

Continuing to fall back to single-replica `system.query_log` on the
ONLINE host that Metabase still reaches. Numbers are 5–10% of full
cluster traffic but the shapes are consistent.

## Local-replica view: steady-state, no slow buckets in EU morning

`q27_local_recent_1h.tsv` — 10-min buckets on the local replica, last
hour (09:40 → 10:35Z), all stats_table tags:

| bucket | tag | cnt | over_5s | p95 ms | max ms |
| ------ | --- | --- | ------- | ------ | ------ |
| 09:40 | main_query | 9 | 0 | 1959 | 2703 |
| 09:50 | main_query | 9 | 0 | 1496 | 1893 |
| 10:00 | main_query | 13 | 0 | 861 | 956 |
| 10:10 | main_query | 7 | 0 | 2587 | 3296 |
| 10:20 | main_query | 5 | 0 | 1144 | 1274 |
| 10:30 | main_query | 8 | 0 | 1764 | 2138 |

**Zero queries >5s across all stats_table tags on this replica in the
last hour.** EU morning peak so far is producing healthy latency — no
user-driven slow clusters visible. The 09:00 burst from team 10085 was a
local event, not a systemic pattern.

## Per-tag local 6h aggregate (no significant change since 1003Z)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 308     | 290       | 1255    | 1254      |
| `web_overview_query`                    | 124     | 114       | 1091    | 1090      |
| `stats_table_path_bounce_query`         | 105     | 92        | 2741    | 2635      |
| `stats_table_frustration_metrics_query` | 92      | 93        | 1821    | 1809      |
| `web_goals_query`                       | 20      | 20        | 2001    | 2001      |
| `stats_table_entry_bounce_query`        | 16      | 13        | 693     | 701       |
| `web_vitals_path_breakdown_query`       | 13      | 12        | 535     | 267       |
| `external_clicks_query`                 | 3       | 3         | 1095    | 1095      |

Web vitals p95 jumped 267 → 535 — team 10085's earlier 27-vitals-query
burst is now partially captured in this replica's 6h window (1095, 821ms
range outliers). Even those weren't slow (no >5s queries from vitals).

No legacy `stats_table_query` rows visible on this replica's 6h view —
consistent with full rollout convergence, but not provable without
cluster visibility.

## Files

- `q11c_local_only_6h.tsv` — local 6h aggregate
- `q11b_offline_cluster.tsv` — empty (offline cluster also failing)
- `q27_local_recent_1h.tsv` — 10-min buckets for last hour, all calm

## Watch list for next iteration

1. Whether `clusterAllReplicas` recovers. If still broken after the next
   iteration, the cluster outage has been going for ~1h — worth flagging
   beyond this skill (it'd affect anyone querying system.query_log via
   Metabase).
2. Whether the EU midday window (11:00–13:00 UTC) produces any new heavy
   activity.
