# Dashboards v2 scorecard

A local before/after benchmark for each step of the [Dashboards v2 roadmap](https://github.com/PostHog/posthog/issues/138125).
Every scenario runs with `dashboard-v2` forced off (today's behaviour), then forced on.
It writes one JSON scorecard and prints a markdown table.

```bash
DEBUG=1 PYTHONPATH=. DJANGO_SETTINGS_MODULE=posthog.settings \
  python products/dashboards/backend/benchmarks/dashboard_v2_scorecard.py --out /tmp/dv2.json
```

- Full mode runs each arm 3 times. It took 13 minutes on master and takes longer as more "after" arms light up. `--quick` runs once per arm with short windows and takes about 2 minutes.
- `--dashboard-v2 off|on|both` picks the arm. `on` forces the flag through `_FORCE_ENABLED_FLAGS`, the set behind `POSTHOG_FEATURE_FLAGS_FORCE_ENABLED`.
- `--scenarios BC` runs a subset. `--repeats N` sets runs per arm. `--md-out` defaults to `--out` with `.md`.
- It needs the local Postgres and Redis. pytest swaps Redis and the Django caches for in-memory fakes, so the run points the Redis client, the limiters and the `default` and `query_cache` caches back at `REDIS_URL`. ClickHouse and Snuffle are not called.
- The scenarios need a Django test database, so the script runs them through pytest against `test_$POSTHOG_DB_NAME` (default `test_posthog_dv2bench`). The first run migrates it, which takes a few minutes.
- `RUN_DASHBOARD_V2_BENCH=1 PGDATABASE=posthog_dv2bench pytest products/dashboards/backend/benchmarks/test_dashboard_v2_scorecard.py` runs quick mode and checks every scenario reports. It is skipped without `RUN_DASHBOARD_V2_BENCH`, so it never runs in CI.

## Scenarios

| Scenario | What it measures                                                                                                                                                                                               | Roadmap step                               |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| A        | A 50-tile metrics board refreshing every 10 s for 120 s, next to a 12-tile analytics board in the same organization. Rejected tile queries, p95 tile latency, analytics p95 against the analytics board alone. | 2, metrics query lane (#138146)            |
| B        | Reading a board of 1, 5, 10, 20 and 50 cached tiles. Postgres queries and server time for one insight GET per tile, against one `cached_tiles` request.                                                        | 1, batched cached read (#138219)           |
| C        | Two viewers refreshing a logs tile 10 times each over 60 s. ClickHouse computes.                                                                                                                               | 4, cacheable logs (#138142)                |
| D        | Hourly warming for a team with 20 stale tiles, 3 of them read in the last 24 h. Tiles warmed and computes.                                                                                                     | 3, warm read tiles only (#138141)          |
| E        | First load of a 300-tile board with 12 tiles on screen, through the modelled client. Tile queries issued and load times.                                                                                       | 2b, visible tiles only (#138169, frontend) |

A step whose code isn't on the branch is reported as `not merged yet` and its "after" arm is skipped.
`--measure-unmerged` runs that arm anyway, and it should then match "before".
Each step's marker (a name its PR adds) is in `STEPS` in `scorecard_scenarios.py`.
The scorecard fills in as each PR merges, with no change here unless a PR renames its marker.

## Real vs mocked

| Real                                                                        | Mocked or modelled                                                                                                                |
| --------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `get_query_runner(...).run()`: cache, limiters, flag checks, access checks  | `_calculate` (the ClickHouse/Snuffle compute): a lognormal sleep behind a 24-slot semaphore, seeded                               |
| App limiters in the local Redis (their `TEST` bypass is lifted for A and E) | gunicorn threads: a 32-slot semaphore                                                                                             |
| Insight and `cached_tiles` endpoints through the Django test client (B)     | The browser: threads that follow `dashboardLogic.tsx` (4 requests in flight per tab, 10 s refresh, a pending tile isn't requeued) |
| Logs widget `run_logs_list_widget` with a pinned clock (C)                  | Celery: the warming scheduler's chain is captured and each task is called directly (D)                                            |
| Cache warming scheduler and `warm_insight_cache_task` (D)                   | Scenario E's visible-only load: the client requests 12 tiles instead of 300 (modelled client)                                     |

Not measured: browser paint, the real HTTP stack in A and E, retries of rejected tiles, and the cost of a real ClickHouse query.
Changing the client constants at the top of `dashboard_load_harness.py` or the mock latencies changes the numbers.

## Noise

Values are medians across runs. The run-to-run range column shows the lowest and highest run of each arm.
Counts that the code decides (B's queries, C, D, E's tile queries) don't vary.
A varies most. A rejected tile returns at once, so its queue drains fast and the rest of that refresh cycle tends to be rejected too. Whether that cascade starts depends on thread timing.
The p95 latencies in A cover served tiles only, measured from when the client queued the tile.
