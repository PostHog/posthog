# Web analytics snapshot — 2026-05-19 11:40 UTC (run-1140Z)

Diff vs run-1108Z. **Cluster outage recurred.**

## Cluster outage is recurring, not a one-shot

Same `ALL_CONNECTION_TRIES_FAILED` error on `clusterAllReplicas` again,
same failing replica URI as 10:00 UTC and 10:36 UTC. So the recovery seen
at 11:08 UTC was transient — the issue is *intermittent*, not resolved.

Pattern so far this morning:

- ~10:00 → ~10:55 UTC: broken
- ~11:00 → ~11:08 UTC: working (run-1108Z succeeded)
- 11:40 UTC: broken again

This crosses an hour of cumulative cluster-blind time. Worth a heads-up
to whoever is on Metabase-or-ClickHouse-infra — anyone using
`clusterAllReplicas` on the prod-us databases via Metabase is hitting
this flicker.

## Could not identify the 22s / 18s outliers

Goal this iteration was to pull `team_id` for the new outliers that
emerged during the prior cluster-blind window (the 22.3s `main_query` and
18.0s `path_bounce` queries from 10:00–11:00 UTC). Local-replica fallback
returned **zero rows** for >10s queries in that window — those slow
queries landed on the other replicas we can't reach right now.

Stalled until cluster is reachable again.

## Local replica: healthy steady-state, no outliers

`q11c_local_only_6h.tsv` for 05:41 → 11:40 UTC on the visible replica:

| Tag                                     | cnt | p95 ms | p99 ms |
| --------------------------------------- | --- | ------ | ------ |
| `stats_table_main_query`                | 313 | 1181   | 2117   |
| `stats_table_frustration_metrics_query` | 95  | 1130   | 2557   |
| `web_overview_query`                    | 94  | 1236   | 1617   |
| `stats_table_path_bounce_query`         | 94  | 1380   | 2436   |
| `web_vitals_path_breakdown_query`       | 20  | 443    | 608    |
| `stats_table_entry_bounce_query`        | 11  | 1086   | 1104   |
| `web_goals_query`                       | 7   | 1095   | 1110   |
| `external_clicks_query`                 | 2   | 579    | 584    |

These are the **lowest p95s I've seen all day** for several tags:
path_bounce p95 1380ms (vs cluster ~2400ms), main_query 1181ms (vs ~1300).
Two interpretations:

1. This replica is genuinely lightly loaded right now — explanatory
   given the cluster-blind situation; queries that would have been
   slow are landing on the unreachable shard.
2. EU midday peak hasn't yet stressed this replica's specific shard
   key range.

The aggregate cluster numbers next iteration will tell.

## Files

- `q11c_local_only_6h.tsv` — local 6h aggregate (full visibility lost)
- `q29_local_outliers.tsv` — empty (the slow outliers aren't on this replica)

## Watch list for next iteration

1. **Whether the cluster outage clears stably**, or continues flapping.
2. If/when cluster is back, identify the 22s + 18s outliers (and any new
   ones from this iteration's window) with `team_id` + query_id.
3. EU midday density: peak should be 11:00–13:00 UTC. Next iteration is
   in the middle of that window.
