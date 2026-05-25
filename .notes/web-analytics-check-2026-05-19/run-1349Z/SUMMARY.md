# Web analytics snapshot — 2026-05-19 13:49 UTC (run-1349Z)

Diff vs run-1317Z. Steady state continues; no new patterns.

## Bucket 1 (automated PAK polling): still just 2 teams

`q34_pak_polling_teams.tsv` — last 1h, PAK consumers with ≥10
web-analytics queries:

| team_id | access      | tag                       | cnt | avg ms | p95 ms | max ms |
| ------- | ----------- | ------------------------- | --- | ------ | ------ | ------ |
| 204248  | PAK         | `web_overview_query`      | 74  | 797    | 1689   | 3543   |
| 125691  | PAK         | `external_clicks_query`   | 36  | 983    | 1741   | 2297   |

Threshold `cnt ≥ 10` over a 1h window returns **only the two teams we've
already characterized**. No third PAK consumer in the heavy-polling band
this hour. The pattern is currently scoped to these two known integrations.

p95 and max columns confirm both teams' "normal" duration profile is in the
1.7–3.5s range; the 8–33s outliers from earlier today aren't recurring as
frequent events — they're rare tail spikes.

## No new extreme outliers in 30 min

`q11b_all_web_tags_6h.tsv` max columns are **unchanged** from run-1317Z:

- `stats_table_main_query` max: 32439 (still team 204248's 12:17 spike)
- `web_overview_query` max: 33542 (still team 204248's 12:17 spike)
- `stats_table_path_bounce_query` max: 20099 (still team 112458 at 12:43)
- `web_goals_query` max: 54960 (still team 2 at 09:08)

So no new dashboard-heavy-load incident from team 10085 / team 112458 in
the last 30 min, and no new spike from the PAK polling teams.

## Per-tag steady state

| Tag                                     | cnt  | avg ms | p95 ms | p99 ms |
| --------------------------------------- | ---- | ------ | ------ | ------ |
| `stats_table_main_query`                | 7306 | 675    | 1306   | 2454   |
| `web_overview_query`                    | 2763 | 667    | 1243   | 2446   |
| `stats_table_frustration_metrics_query` | 2280 | 614    | 1201   | 2140   |
| `stats_table_path_bounce_query`         | 2184 | 1206   | 2334   | 4568   |
| `web_vitals_path_breakdown_query`       | 540  | 292    | 679    | 1052   |
| `web_goals_query`                       | 335  | 1110   | 2457   | **5241** |
| `stats_table_entry_bounce_query`        | 313  | 670    | 1313   | 2262   |
| `external_clicks_query`                 | 170  | 924    | 2073   | 7180   |
| `stats_table_path_bounce_and_avg_time_query` | 1 | 2778   | 2778   | 2778   |

Only notable change: `web_goals_query` p99 5241 (was 3878) — some new
goals queries in the 4–5s band entered the window. Worth a glance next
iteration; not concerning yet.

Tag counts continue rising as expected with steady traffic: main_query
6896 → 7306 (+410 in 30m). external_clicks 148 → 170 (+22, consistent
with team 125691's ~18 queries/30m).

## Cluster: stable

`clusterAllReplicas` worked first try this iteration. ~1h since the last
observed outage tick. May be stably recovered; or may still be flapping
on a slower cadence.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q34_pak_polling_teams.tsv` — confirms PAK polling Bucket 1 is just 2 teams

## Watch list for next iteration

1. Whether the elevated `web_goals_query` p99 (5241ms) sustains or was
   transient.
2. Cluster outage recurrence.
3. Any new entry in the PAK polling band (would indicate a third common
   integration pattern).
