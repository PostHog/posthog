# Querying, caching, and scale

## Query and cache contract

Dashboard load and dashboard refresh are different operations.

- `posthog/hogql_queries/refresh_policy.py` defines default execution mode by `ComputeSurface`.
- Explicit client refresh settings override the surface default.
- Shared rendering is clamped last. It must not force a blocking recompute.
- `dashboardLogic` refreshes stale insight tiles and tracks queued, loading, cached, and failed results.
- `run_insights` is a separate endpoint from dashboard detail and dashboard streaming. Keep their cache and error behavior separate.

Before changing a query path, answer these questions.

1. Does normal dashboard load return cache-only results, cached data, or a synchronous query?
2. Which caller can force a refresh?
3. What happens when the cache is stale or empty?
4. How does one tile failure affect the remaining tiles?
5. What cancels work after navigation or a new dashboard load?
6. Which access method records cache hits and misses?

## Keep work bounded

Treat a dense dashboard as the default performance boundary.

- Do not issue one unbounded request per tile.
- Prefetch all data serializers need. Avoid per-tile database queries in dashboard serialization.
- Do not compute expensive template diagnostics in a template list response.
- Avoid N full-grid renders while individual tile results arrive.
- Cancel in-flight work when dashboard identity, filters, variables, or placement changes.

If the change affects a widget query, read `manage-dashboard-widgets`. Do not duplicate its batch, throttle, or result-limit rules here.

## Test scale deliberately

Use representative fixtures or test helpers. Do not depend on production data.

| Case                      | Expected result                                             |
| ------------------------- | ----------------------------------------------------------- |
| Empty dashboard           | Fast empty state. No tile query.                            |
| One tile                  | Correct content and controls.                               |
| Many insight tiles        | Bounded requests, stable loading state, independent errors. |
| Mixed tiles               | Text and buttons do not enter query refresh paths.          |
| Slow or failed tile       | Other tiles remain usable. Error is tile-scoped.            |
| Repeated refresh          | No duplicate requests for the same refresh window.          |
| Navigation during refresh | Abort or ignore obsolete responses.                         |

## Observability

- Preserve dashboard access counters by `human`, `shared`, `embedded`, and `api` access method.
- Preserve cache hit and miss counters for dashboard insight results.
- Preserve endpoint monitoring for dashboard reads. Assess SLO coverage when a new delivery or query path changes user-visible latency.
- Do not use instrumentation as a substitute for a concurrency or cache bound.

## Verification

Run the smallest relevant set first.

```bash
hogli test products/dashboards/backend/api/test/test_run_insights.py
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test frontend/src/scenes/dashboard/dashboardLogic.test.ts
hogli test frontend/src/scenes/dashboard/DashboardItems.test.tsx
```

Also run focused tests for the changed API, sharing, template, or layout behavior.
