# Choosing a fix

Pick the cheapest fix that keeps the customer's answer the same. Measure the before and after cost with queries.md section 9.

## Rewrites

| Pattern in their SQL                                                     | Rewrite                                                                                                                                                                               |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WITH x AS (SELECT ... FROM events ...) SELECT ... FROM events e JOIN x` | One pass: `GROUP BY person_id`, collect the second event type with `groupArrayIf(tuple(...), event = '...')`, filter with `HAVING`, then `ARRAY JOIN`. It removes the nested fan-out. |
| One query per segment, time window, or period of the same job            | One query that returns every segment, window, or period as a column. The caller filters.                                                                                              |
| A fixed start date to `now()`, rerun every few minutes                   | Compute finished periods once (a view with a period column) and query only the current period live.                                                                                   |
| MCP results that stop at the row cap                                     | Not a rewrite. The rows were cut off silently. Check the endpoint's row behavior (limits.md) and suggest an endpoint if it pages past the cap.                                        |

When you test a ClickHouse-level rewrite such as `GLOBAL JOIN`, check that HogQL can express it (`posthog/hogql/grammar/HogQLParser.g4`). Then write the HogQL form and confirm it compiles to the same fan-out.

## Materialize as a view or an endpoint

- A materialized endpoint is a saved query plus a freshness setting, called by name with variables. Use it when an agent or backend fetches the result on a schedule.
- A materialized view is a table that other queries read with `FROM <view>`. Use it when several queries share one base result.
- Find the current UI path and labels for both on `origin/master` before you name them, for example `git grep -n 'Materialize' origin/master -- frontend products`.
- It only reduces load if the customer accepts the refresh interval. Compare `(cost per refresh) × (refreshes per hour)` with `(cost per run) × (runs per hour)` today. Get both costs from probes, not estimates.
- Check whether refreshes are full rebuilds or incremental, and which cluster they run on in this region (limits.md). A full rebuild over a growing window costs more every day, so say that in the handoff.
- Check `can_materialize_query` rules in limits.md before suggesting an endpoint.

## Cache

- Exact repeats spaced wider than the SQL cache freshness (limits.md) always miss the cache. Repeats inside it that still reach ClickHouse usually come from a forced refresh.
- Most repeats are polls for fresh data (`now()`-relative or open-ended windows). Serving them a cached or materialized result changes the answer, so don't suggest that silently.

## Not worth fixing

Say why in one line: cheap in total, rarely run, or needs fresh data every run and is already efficient.

## Don't materialize on the customer's behalf

Suggest materialization and let the customer choose the freshness.
Exact repeats are a caching problem, and a scheduled refresh costs load even when nobody reads the result.
Most repeats want fresh data.
Merging same-shape queries needs judgment about semantics.
Views also appear in the customer's project with no owner to delete them.
