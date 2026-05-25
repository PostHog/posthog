# Web analytics snapshot — 2026-05-19 11:08 UTC (run-1108Z)

Diff vs run-1036Z. Cluster is back.

## Cluster query recovered. Outage ~1 hour.

`clusterAllReplicas(posthog, system, query_log)` works again. Roughly:

- First failure: ~10:00 UTC (first attempt in run-1003Z)
- Confirmed still down: 10:36 UTC (run-1036Z)
- Confirmed back: 11:08 UTC (this run)

Total outage window: roughly 1h–1h10. Affected both ONLINE and OFFLINE
clusters' cross-replica queries (different failing replicas on each), so
the most plausible root cause is a Metabase-host network/credentials
issue, not two independent ClickHouse incidents.

## Legacy `stats_table_query` is officially dead

`q28_legacy_8h.tsv` over last 8h: 18 total rows of legacy `stats_table_query`,
**all between 03:22:46Z and 04:09:51Z**. Last emit at 04:09:51Z — earlier
than the 04:15:19Z figure I'd been carrying (the prior `last_seen` in 6h
aggregates was the latest-still-in-window value, not the truly-last emit).

The full-cluster rollout therefore fully converged by 04:10 UTC.

- 21:00 → 04:10 UTC: legacy + new tags coexisting (~7h overlap window)
- 04:10 UTC onward: only new tags emit

No more mentions of legacy `stats_table_query` going forward.

## Per-tag 6h numbers — first full-cluster view in ~1h

| Tag                                     | cnt   | avg ms | p95 ms | p99 ms | max ms |
| --------------------------------------- | ----- | ------ | ------ | ------ | ------ |
| `stats_table_main_query`                | 6101  | 665    | 1278   | 2467   | **22323** |
| `web_overview_query`                    | 2267  | 633    | 1207   | 2390   | **27447** |
| `stats_table_frustration_metrics_query` | 1940  | 606    | 1255   | 2526   | 7809   |
| `stats_table_path_bounce_query`         | 1874  | 1185   | 2372   | 4693   | **18007** |
| `web_vitals_path_breakdown_query`       | 352   | 272    | 607    | 882    | 1614   |
| `web_goals_query`                       | 325   | 1031   | 2300   | 3169   | **54960** |
| `stats_table_entry_bounce_query`        | 285   | 632    | 1107   | 1807   | 2620   |
| `external_clicks_query`                 | 90    | 616    | 1381   | 1533   | 1565   |
| `stats_table_path_bounce_and_avg_time_query` | 1 | 2778   | 2778   | 2778   | 2778   |

**max columns confirm prior extreme outliers still in window**:

- `web_goals_query` max **54960ms** — team 2's monster query at 09:08
- `web_overview_query` max **27447ms** — team 2's 09:07 follow-up
- `stats_table_main_query` max **22323ms** — new since prior cluster view;
  likely a fresh outlier worth chasing on the next iteration
- `stats_table_path_bounce_query` max **18007ms** — also new (was 14477)

So in the cluster-blind window (10:00–11:00 UTC), at least two new
extreme outliers appeared: one main_query >22s and one path_bounce >18s.
Worth pulling their identities.

## Steady-state shape is healthy

- p95s across all tags are in their expected bands (path_bounce ~2.4s,
  main_query ~1.3s, goals ~2.3s, overview ~1.2s).
- `external_clicks_query` p95 1381ms — coming down to a steady value as
  rollout converges.
- The other path_bounce variant tags are emitting on schedule.

## Files

- `q11b_all_web_tags_6h.tsv` — first full-cluster view since 10:00 UTC outage
- `q28_legacy_8h.tsv` — confirms legacy `stats_table_query` last emit 04:09:51Z

## Watch list for next iteration

1. Pull `team_id` for the new 22s `main_query` and 18s `path_bounce`
   outliers that appeared during the cluster outage.
2. Whether the cluster outage recurs (could be ongoing intermittent
   issue rather than fully resolved).
3. EU midday ramp: 11:00–13:00 UTC is the densest traffic window of the
   day, good signal for whether load stresses the system.
