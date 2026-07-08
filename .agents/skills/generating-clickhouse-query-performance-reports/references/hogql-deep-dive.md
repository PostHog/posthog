# HogQL deep dive

`lc_query__kind = 'HogQLQuery'` is its own analysis bucket because, unlike product-generated insights
(TrendsQuery, FunnelsQuery, ...), HogQL is **arbitrary user- or AI-authored SQL**. It runs from the SQL
editor / DataVisualization node (web), the `/query/` API (`personal_api_key` / `oauth`), the MCP server,
and the Max assistant. It bypasses the guardrails that shape product insights (no enforced date range,
no materialization-aware property access, arbitrary joins), so its slowness causes are more varied and
it is over-represented among OOMs and timeouts.

Two columns matter for HogQL:

- `query` — the compiled ClickHouse SQL that actually ran.
- `lc_query__query` — the **source HogQL** the user or AI wrote. Read this to see intent; it is far
  shorter and clearer than the compiled SQL, and the `query_link` recipe (`query-patterns.md` §6)
  already selects it.

## Landscape: who issues the slow HogQL

```sql
SELECT
    lc_product, lc_feature, lc_access_method,
    count() AS slow,
    uniqExact(team_id) AS teams,
    countIf(exception_code = 241) AS ooms,
    countIf(exception_code = 159) AS timeouts,
    round(avg(query_duration_ms)/1000) AS avg_s,
    formatReadableSize(sum(read_bytes)) AS total_read
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query
    AND lc_query__kind = 'HogQLQuery'
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
GROUP BY lc_product, lc_feature, lc_access_method
ORDER BY slow DESC LIMIT 40
```

The bulk is `product_analytics` / `query` / `personal_api_key` (data integrations and API consumers).
Tight-timeout API noise (avg ~13s, mostly timeouts) and `cache_warmup` (background insight refresh)
dominate raw counts; weigh by OOMs and cluster-hours as usual.

## Identifying AI-written HogQL

There is **no single boolean "written by AI" column.** Identify it from `lc_product` + `lc_feature`:

| Signal                                       | Means                                                                                                              |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `lc_product = 'max_ai'`                      | PostHog's Max assistant and its tools (tagged via `tags_context(product=Product.MAX_AI)` throughout `ee/hogai/**`) |
| `lc_product = 'mcp'` or `lc_feature = 'mcp'` | Queries issued by external AI agents through the PostHog MCP server                                                |
| `lc_feature = 'posthog_ai'`                  | The AI feature tag (also exists; less common in practice)                                                          |

Filter: `lc_product IN ('max_ai','mcp') OR lc_feature IN ('mcp','posthog_ai')`.

**Do not use `ai_query_source`.** Despite the name it records which AI-events table the LLM-analytics
resolver chose (`dedicated_table` / `shared_table_fallback`), not "AI authored this".
It is also not materialized as an `lc_*` column in the archive.

Caveats:

- This flags queries executed _within_ an AI/MCP context. An insight Max drafts that a human then saves
  and reloads is re-tagged as normal `product_analytics`; the archive cannot tell it was AI-originated.
- Heuristic tell: AI-written HogQL often carries explanatory `-- …` comments in `lc_query__query`
  (people rarely comment ad-hoc SQL). Useful as a secondary signal, not authoritative.
- Source of truth for the tags: the `Product` / `Feature` enums and the product-from-node-kind mapping
  in `posthog/clickhouse/query_tagging.py`; call sites in `ee/hogai/**` and the MCP server.

```sql
SELECT
    lc_product, lc_feature, lc_access_method,
    count() AS slow,
    uniqExact(team_id) AS teams,
    countIf(exception_code = 241) AS ooms,
    countIf(exception_code = 159) AS timeouts,
    round(100 * countIf(exception_code = 241) / count()) AS oom_pct
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 14 DAY AND is_initial_query
    AND lc_query__kind = 'HogQLQuery'
    AND (lc_product IN ('max_ai','mcp') OR lc_feature IN ('mcp','posthog_ai'))
    AND (query_duration_ms > 30000 OR exception_code IN (159,160,241))
GROUP BY lc_product, lc_feature, lc_access_method
ORDER BY slow DESC
```

AI/MCP HogQL OOMs and times out at a disproportionately high rate (the MCP-over-OAuth bucket has seen
roughly a third of its slow queries OOM in a single week), because these are ambitious analytical
queries written without the guardrails of product-generated insights.

## What makes AI / ad-hoc HogQL slow

Read `lc_query__query` on the slow set; the recurring causes:

- **Unmaterialized JSON extraction.** The AI writes `JSONExtractString(properties, 'x')` or
  `properties.x` on event or person properties. The `JSONExtract*(...)` call form bypasses
  materialization (see the
  [`optimizing-clickhouse-and-hogql-queries`](../../optimizing-clickhouse-and-hogql-queries/references/investigation-playbook.md)
  investigation playbook and `materialization-analysis.md`), forcing a full JSON-blob read per row.
- **Self-joins and cross joins on `events`.** e.g. `events e1 JOIN events e2` on person within a time
  window, or `CROSS JOIN` with a per-person aggregate. Multiplies the scan.
- **Cross-source joins.** Joining warehouse tables (`postgres.*`, `vitally.*`, `s3(...)`) against
  events; the external side has no ClickHouse indexing.
- **No or wide date range.** Ad-hoc SQL often omits a tight `timestamp` filter, scanning all history.
- **Full exports ordered by a wide column.** See the function-wrapped sort/filter-key anti-pattern in
  the [`optimizing-clickhouse-and-hogql-queries`](../../optimizing-clickhouse-and-hogql-queries/references/investigation-playbook.md)
  investigation playbook.

To inspect one AI query, pull both forms:

```sql
SELECT lc_query__query AS source_hogql, query AS compiled_sql, exception
FROM posthog.query_log_archive
WHERE query_id = '<id>' AND event_date = '<YYYY-MM-DD>' AND is_initial_query
```
