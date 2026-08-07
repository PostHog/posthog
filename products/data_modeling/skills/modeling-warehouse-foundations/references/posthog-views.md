# PostHog-native modeling: views & materialized views

A **view** (a.k.a. saved query) is a named HogQL `SELECT` stored in the project. By default it is
**virtual** — it re-runs every time something reads it. **Materializing** it computes it once into a
physical table on a schedule, so reads are fast and cheap. Views are written and managed over MCP with the
`view-*` tools; their inventory is read back through `information_schema` (below).

## Reading what exists

To list views, inspect their columns, or check materialization status, query `information_schema` with
`posthog:execute-sql` rather than a per-view tool — it stays correct as the toolset changes and is the same
discovery path the rest of these skills use:

```sql
SELECT table_name FROM system.information_schema.tables WHERE table_name ILIKE '%my_view%'
-- columns: system.information_schema.columns; accepted joins: system.information_schema.relationships
```

The one thing `information_schema` can't give you is the `edited_history_id` concurrency token — fetch that
with `posthog:view-get` right before a `view-update` that changes the query.

## The write tools

These are the tools that change state. Treat this as a map, not a spec: the toolset evolves, so confirm the
current set and each tool's exact inputs by inspecting the tool itself (`posthog:exec info <tool>` /
`posthog:exec schema <tool>`) rather than trusting an enumerated list here.

| Tool                                            | Purpose                                                                                                                                                     |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog:view-create`                           | Create (or upsert) a view from HogQL. Same `name` → updates the existing view.                                                                              |
| `posthog:view-update`                           | Change name / query / description / sync frequency. Editing the query re-infers columns and needs the current `edited_history_id` (optimistic concurrency). |
| `posthog:view-materialize`                      | Turn a virtual view into a materialized table + a sync schedule. Rate-limited.                                                                              |
| `posthog:view-run` / `posthog:view-run-history` | Trigger a materialization refresh now (must already be materialized) / read recent run statuses to debug failures.                                          |
| `posthog:view-unmaterialize`                    | Drop the physical table + schedule; keep the view definition as virtual.                                                                                    |
| `posthog:view-delete`                           | Soft-delete a view. Refused if other views depend on it, or if it's owned by a managed viewset (e.g. `revenue_analytics_*`).                                |
| `posthog:saved-query-column-annotations-*`      | Attach human/agent-readable descriptions to the view and its columns (discoverability).                                                                     |

## The workflow

1. **Write and test the HogQL first** with `posthog:execute-sql` until the result is correct. Read
   `querying-posthog-data` for HogQL syntax and the schema-discovery workflow. Confirm events/properties
   exist before referencing them.
2. **Alias every output column.** `view-create` rejects `SELECT *` and any bare column — every selected
   expression needs `AS <name>`. This is the most common create failure.

   ```sql
   -- rejected: SELECT toStartOfMonth(timestamp), count() FROM events ...
   -- accepted:
   SELECT toStartOfMonth(timestamp) AS month,
          count()                    AS events
   FROM events
   GROUP BY month
   ```

3. **Create it:** `posthog:view-create {"name": "monthly_events", "query": {"kind": "HogQLQuery", "query": "..."}}`.
   (Inspect the exact input shape once with `posthog:exec info view-create` / `schema view-create query`.)
   Names are lowercase snake_case, unique, and become the table name you query later.
4. **Verify:** confirm the inferred columns via `system.information_schema.columns` (use `view-get` if you
   need to see a `latest_error`).
5. **Materialize only if it earns it** (see below), then set an appropriate `sync_frequency`.

## Virtual vs materialized — when to materialize

Materialize when **at least one** holds:

- The query is **expensive** (large scans, heavy joins, window functions) and read often.
- It's **reused** by dashboards, other views, or downstream models — pay the compute once.
- It's a **slowly-changing dimension** (country/plan/currency lookup) that changes far less often than it's
  read. Pair a static dimension with a slow `sync_frequency`.

Leave it **virtual** when the query is cheap, ad-hoc, or needs up-to-the-second freshness. Materialized reads
are stale up to one `sync_frequency` interval.

Set `sync_frequency` to match how fast the data changes and how fresh readers need it — a daily-rebuilt
country dimension is fine at a daily or weekly cadence; a near-real-time funnel wants an hourly one. The tool
takes a fixed set of interval values, so read the accepted ones from the `view-materialize` (or `view-update`)
schema — `posthog:exec schema view-materialize` — rather than assuming. Materialization runs get extra compute
but still time out after ~1 hour, so materialize a bounded query, not an unbounded full-history scan.

## Nesting

A view can select from another view (`FROM my_other_view`). Compose a raw/staging view → a metric view, the
same layering dbt does with `staging/` → `marts/`. Materialize the expensive lower layer; keep thin wrappers
virtual. `view-delete` refuses to remove a view that others depend on — delete top-down.

## Cleanup (important for throwaway/validation views)

When you create a view just to validate a recipe, remove it afterwards: `view-unmaterialize` (if you
materialized it) then `view-delete`. Don't leave test views littering the project.
