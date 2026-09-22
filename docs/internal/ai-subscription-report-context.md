# Saved context in AI subscription reports

There is no flattening layer that pre-computes and formats every selected dashboard and insight
before the model runs. Instead, the planner and synthesis models fetch saved context on demand
through three in-process tools: `list_selected_contexts`, `fetch_insight`, and `fetch_dashboard`.

`ContextToolRuntime` enforces the allowlist, viewer access, and read budget inside the tools
themselves, never through prompt instructions. Only dashboards and insights attached to the
subscription resolve. Viewer access is checked at two points, not on every fetch: once when the
runtime loads, before any tool call runs, and again at delivery time (see below). A viewer access
revocation that happens mid-generation is caught by the delivery-time recheck before the recipient
sees the result.

`MAX_SELECTED_CONTEXTS` bounds how many dashboards and insights a subscription may attach. A
selection over that cap fails every attached context closed rather than silently using the first
`MAX_SELECTED_CONTEXTS` of them. `MAX_CONTEXT_READ_BUDGET` separately bounds how many of them one
report generation may actually fetch, regardless of how many tool calls the model makes.

HogQL repair never receives saved result rows. It gets a schema-only snapshot carrying table,
field, event, property, and group names only: built from each successfully fetched context's
`format_schema()`, or, on a frozen-plan run where nothing has been fetched yet, from the
registered contexts' schemas captured at load time.

Each dashboard's and insight's status (id, name, success/failed) persists compactly on the
delivery snapshot; no fetched content is stored alongside it. A third status, `truncated`, exists
only for historical rows written before that status stopped being produced.

The tool loop's own limits are round and concurrency caps, not time bounds: `MAX_TOOL_ROUNDS` on
the loop and `MAX_CONCURRENT_CONTEXT_FETCHES` on tiles fetched within one `fetch_dashboard` call.
The only wall-clock bound on context work is the report's overall generation deadline.

At delivery, the subscription creator's access to every fetched context ref is re-checked against
their current permissions rather than trusted from generation time.
