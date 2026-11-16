# Dashboard load harness

Backend-only replay of the dashboard frontend's request pattern. It prints one JSON line and a final `SCORE=<n>` (lower is better).

```bash
DEBUG=1 PYTHONPATH=. DJANGO_SETTINGS_MODULE=posthog.settings \
  .venv/bin/python products/dashboards/backend/benchmarks/dashboard_load_harness.py          # ~5 min
  ... --quick                                                                                  # ~1.5 min smoke
```

Needs only the local Redis (port 6379). It uses a unique org id and deletes its keys.

## What it measures

- **M1**: a 50 tile `metrics` board auto refreshing every 10s for 120s. Reports rejected (`ConcurrencyLimitExceeded`, the 429 path) requests, p50/p95 tile latency including client queue wait, and events queries triggered.
- **M3**: a 12 tile `analytics` board in the same org, refreshing alongside M1. Reports its rejections and latency, plus a run of it alone for comparison.
- **M2**: first load of a 50 tile board (p95 over `--load-runs`) and of a 300 tile board (queries issued). `--load-mode visible` models a viewport-only load.

## Real vs mocked

| Real                                                                                                     | Mocked                                                               |
| -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `get_app_org_rate_limiter` and `get_app_dashboard_queries_rate_limiter` (Lua script, Redis, limit of 6)  | ClickHouse and Snuffle: a lognormal sleep behind a 24-slot semaphore |
| Limiter nesting order from `QueryRunner.run`                                                             | gunicorn threads: a 32-slot semaphore                                |
| Client queue width 4, 10s interval, tiles skipped while still pending (modelled on `dashboardLogic.tsx`) | The client itself: threads, not a browser                            |

Not measured: browser paint time (`first_paint_ms` is only the cached-read stub), the `streamTiles` SSE path, real `MetricsQueryRunner` cost, the real HTTP stack, rejected tiles retrying. `events_queries_triggered` is 0 unless `--count-analytics-in-m1` is set, because a metrics tile never touches the events table in this model. If a future change routes refreshes through events queries, wire the real call count in.

Changing `DEFAULT_APP_DASHBOARD_CONCURRENT_QUERIES`, the limiter wiring, or the client constants (mirrored at the top of the script) changes the numbers. Changing frontend behavior does not, until the constants or the request pattern in the script are updated to match.

## Score

`m1.rejected + m3.rejected + m1.events_queries + m1.p95_ms/100 + max(0, m3.p95 - m3_alone.p95)/100 + m2_50.fully_loaded_p95_ms/1000 + m2_300.tile_queries/10`

## Baseline (master 6ea50cb16cd, `--out` run)

M1 189/598 rejected, p95 8137ms. M3 107/144 rejected, p95 1222ms (alone 1182ms). M2 50 tiles fully loaded p95 11179ms. M2 300 tiles issued 300 queries. SCORE=418.95.
