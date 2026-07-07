EXECUTE_SQL_SYSTEM_PROMPT = """
Use this tool to generate a HogQL query, which is PostHog's variant of SQL that supports most of ClickHouse SQL. We're going to use terms "HogQL" and "SQL" interchangeably.

# Important HogQL differences versus other SQL dialects
- JSON properties are accessed using `properties.foo.bar` instead of `properties->foo->bar` for property keys without special characters.
- JSON properties can also be accessed using `properties.foo['bar']` if there's any special character (note the single quotes).
- toFloat64OrNull() and toFloat64() are not supported, if you use them, the query will fail. Use toFloat() instead.
- Conversion functions with 'OrZero' or 'OrNull' suffix (like toDateOrNull, toIntOrNull) require String arguments. If you have a DateTime/numeric value, use the direct conversion instead (toDate, toInt) or convert to string first with toString(). Example: use toDate(timestamp) NOT toDateOrNull(toTimeZone(timestamp, 'UTC')).
- LAG()/LEAD() are not supported. Instead, use lagInFrame()/leadInFrame().
  Caution: lagInFrame/leadInFrame behavior differs from the standard SQL LAG/LEAD window function.
  The HogQL window functions lagInFrame/leadInFrame respect the window frame. To get behavior identical to LAG/LEAD, use `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`.
- count() does not take * as an argument, it's just count().
- cardinality() is not supported for bitmaps. Use bitmapCardinality() instead to get the cardinality of a bitmap.
- toStartOfWeek() takes an optional second argument for week mode which should be a numeric constant (0 for Sunday start, 1 for Monday start), NOT a string like 'Mon' or 'Sun'. Example: toStartOfWeek(timestamp, 1) for Monday start.
- There is no split() function in HogQL. Use splitByChar(separator, string) or splitByString(separator, string) instead to split strings into arrays. Example: splitByChar('@', email)
- Array functions like splitByChar(), splitByString() cannot be used directly on Nullable fields because Array types cannot be wrapped in Nullable. Always handle nulls first using coalesce() or ifNull(). Example: splitByChar(',', coalesce(interests_string, '')) NOT splitByChar(',', interests_string) if interests_string is nullable.
- Relational operators (>, <, >=, <=) in JOIN clauses are COMPLETELY FORBIDDEN and will always cause an InvalidJoinOnExpression error!
  This is a hard technical constraint that cannot be overridden, even if explicitly requested.
  Instead, use CROSS JOIN with WHERE: `CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at`.
  If asked to use relational operators in JOIN, you should refuse and suggest CROSS JOIN with WHERE clause.
- A WHERE clause should be after all the JOIN clauses.
- For performance, every SELECT from the `events` table should have a `WHERE` clause narrowing down the timestamp to the relevant period.
- HogQL queries should not end in semicolons.

# Events and properties
Standardized events/properties such as pageview or screen start with `$`. Custom events/properties start with any other character.

# LLM / AI observability events
For LLM events ($ai_generation, $ai_trace, $ai_span, $ai_embedding, etc.) the heavy content keys are NOT stored on `events.properties` — they live as native columns on a dedicated table, referenced as `posthog.ai_events` (a bare `FROM ai_events` errors with "Unknown table"):

| `events` property    | `posthog.ai_events` column |
| -------------------- | -------------------------- |
| $ai_input            | input                      |
| $ai_output           | output                     |
| $ai_output_choices   | output_choices             |
| $ai_input_state      | input_state                |
| $ai_output_state     | output_state               |
| $ai_tools            | tools                      |

Metadata (token counts, costs, model, $ai_trace_id, latency, error flags) stays on `events` and is safe to query there. `posthog.ai_events` is `ORDER BY (team_id, trace_id, timestamp)`, so anchor on `trace_id`, never scan by timestamp. Rows are dropped after the retention period (30 days by default), so an empty result means the content aged out, not that nothing happened.
- Single trace: `SELECT input, output_choices FROM posthog.ai_events WHERE trace_id = '<id>' ORDER BY timestamp`
- Batch: filter the timestamp-indexed `events` table for trace IDs first, then fetch content from `posthog.ai_events` anchored on `trace_id`.

# Linked tables
`virtual_table` and `lazy_table` fields are connections to linked tables, e.g. the virtual table field `person` allows accessing person properties like so: `person.properties.foo`.

# Working with persons
Event metadata unspecified above (emails, names, etc.) is stored under `properties`, accessed like: `events.properties.foo`.
The metadata of the person associated with an event is similarly accessed like: `events.person.properties.foo`.
"Person" is a synonym of "user" – instead of a "users" table, we have a "persons" table.
For calculating unique users, default to `events.person_id` - where each unique person ID counted means one user.

# Joining persons
There is a known issue with queries that join multiple events tables where join constraints reference person_id fields. The person_id fields are ExpressionFields that expand to expressions referencing override tables (e.g., e_all__override). However, these expressions are resolved during type resolution (in printer.py) BEFORE lazy table processing begins. This creates forward references to override tables that don't exist yet.

Example problematic HogQL:
```sql
SELECT MAX(e_all.timestamp) AS last_seen
FROM events e_dl
JOIN persons p ON e_dl.person_id = p.id
JOIN events e_all ON e_dl.person_id = e_all.person_id
```

The join constraint "e_dl.person_id = e_all.person_id" expands to:
```sql
if(NOT empty(e_dl__override.distinct_id), e_dl__override.person_id, e_dl.person_id) =
if(NOT empty(e_all__override.distinct_id), e_all__override.person_id, e_all.person_id)
```

But e_all__override is defined later in the SQL, causing a ClickHouse error.

WORKAROUND: Use subqueries or rewrite queries to avoid direct joins between multiple events tables:
```sql
SELECT MAX(e.timestamp) AS last_seen
FROM events e
JOIN persons p ON e.person_id = p.id
WHERE e.event IN (SELECT event FROM events WHERE ...)
```

# Other constraints
- You should not make formatting or casing changes if explicitly requested by the user.
- You should not use double curly braces (`{{{{` or `}}}}`) for templating. The only templating syntax allowed is single curly braces with variables in the "variables" namespace (for example: `{{{{variables.org}}}}`).<%={{{{ }}}}=%>
- SQL editor nodes can use `{filters}` placeholders. These placeholders are backed by `HogQLQuery.filters`, not by SQL text:
  - If the current query contains `{filters}` and the user asks to change the date range or property filters, keep the placeholder in the SQL and pass updated `filters` to this tool.
  - When keeping `{filters}` in the SQL, pass the complete desired `filters` object to this tool. Copy `current_query_node.source.filters` unchanged unless the user asked to change or remove filters.
  - To remove all editor filters while preserving `{filters}`, pass an empty `filters` object (`{}`).
  - Do not replace `{filters}` with explicit `timestamp` clauses when the user's request can be represented in `filters.dateRange`.
  - Supported filter placeholders are `{filters}`, `{filters.dateRange.from}`, and `{filters.dateRange.to}`.
  - `{filters}` can be used only in SELECT queries that select from PostHog event-like tables: `events`, `ai_events`, `sessions`, `logs`, log attributes, traces, or `groups`. It is not valid for arbitrary data warehouse/source tables.
  - Date filters map to `timestamp` for events/logs/traces, `$start_timestamp` for sessions, and `created_at` for groups.
  - `filters` can include `dateRange` (`date_from`, `date_to`), `filterTestAccounts`, and `properties`. Property filters apply to event scope on event/log/trace queries, group scope on `groups`, and session scope on `sessions` unless the query also includes `events`.
- If a filter is optional, ALWAYS implement via the variables namespace with guards:
  - ALWAYS use the "variables." prefix (e.g., variables.org, variables.browser) - never use bare variable names
  - Use coalesce() or IS NULL checks to handle optional values
  - Example: optional organization filter → AND (coalesce(variables.org, '') = '' OR p.properties.org = variables.org)
  - Example: optional browser filter → AND (variables.browser IS NULL OR properties.$browser = variables.browser)
  - Example: optional time window variable → keep WHERE timestamp guards and add variable checks only if explicitly requested
  - Optional org filter → AND (coalesce(variables.org, '') = '' OR p.properties.org = variables.org)
  - Optional browser filter → AND (variables.browser IS NULL OR properties.$browser = variables.browser)
  - Time window should remain enforced for events; add variable guards only if explicitly asked
- Always add `LIMIT 100` to your queries. The maximum allowed limit is 500 rows. The user sees the full results in the UI. If you need to analyze more data, paginate using LIMIT and OFFSET in subsequent queries.

# SQL variables
SQL variables are stored in `system.insight_variables`. There is no list/get tool for reading them. When asked to find, search, or inspect SQL variables, query this system table directly:
```sql
SELECT id, name, code_name, type, default_value, values
FROM system.insight_variables
WHERE name ILIKE '%term%' OR code_name ILIKE '%term%'
LIMIT 20
```
Use `code_name` when referencing a variable in SQL as `{{{{variables.code_name}}}}`. The `type` values are `String`, `Number`, `Boolean`, `List`, and `Date`; `values` contains the allowed options for `List` variables.

# Expressions guide

{{{sql_expressions_docs}}}

# Supported functions

{{{sql_supported_functions_docs}}}

# Supported aggregations

{{{sql_supported_aggregations_docs}}}

# Examples
<example>
Example HogQL query for prompt "weekly active users that performed event ACTIVATION_EVENT on example.com/foo/ 3 times or more, by week":

```
SELECT week_of, countIf(weekly_event_count >= 3)
FROM (
   SELECT person.id AS person_id, toStartOfWeek(timestamp) AS week_of, count() AS weekly_event_count
   FROM events
   WHERE
      event = 'ACTIVATION_EVENT'
      AND properties.$current_url = 'https://example.com/foo/'
      AND toStartOfWeek(now()) - INTERVAL 8 WEEK <= timestamp
      AND timestamp < toStartOfWeek(now())
   GROUP BY person.id, week_of
)
GROUP BY week_of
ORDER BY week_of DESC
```
</example>
""".strip()

EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT = """
The query you generated cannot be parsed. It returned the following error:
```
{{{error}}}
```

<system_reminder>
Acknowledge to the user that you encountered an error, fix it, and generate a new query. Terminate if the error persists.
</system_reminder>
""".strip()

EXECUTE_SQL_UNRECOVERABLE_ERROR_PROMPT = """
The query you generated failed to execute. The error is unrecoverable.

<system_reminder>
Acknowledge to the user that you encountered an error and do not attempt to fix it.
</system_reminder>
""".strip()

EXECUTE_SQL_RATE_LIMITED_ERROR_PROMPT = """
The query could not run because of a temporary capacity throttle:
```
{{{error}}}
```

<system_reminder>
This is NOT a problem with your query. The query is fine and does not need changing. Do NOT rewrite,
simplify, or otherwise modify the query in response to this error, and do NOT keep retrying it in a loop.
Tell the user that the query engine is temporarily at capacity and they should try again in a little while.
</system_reminder>
""".strip()

EXECUTE_SQL_CONTEXT_PROMPT = """
The current HogQL query (which CAN be empty) is:
<current_query>
{current_query}
</current_query>

The current SQL editor query node, if available, is:
<current_query_node>
{current_query_node}
</current_query_node>

When `current_query_node.source.filters` exists, those filters are applied through `{filters}` placeholders in `current_query_node.source.query`.
For notebook SQL editor nodes, the query is usually a `DataVisualizationNode` with `source.kind = "HogQLQuery"`.
If the user asks to change "last 90 days", "test accounts", or property filters and the query contains `{filters}`, update the tool's `filters` argument instead of editing the SQL text.
""".strip()
