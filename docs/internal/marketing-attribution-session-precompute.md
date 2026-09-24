# Attribution session precompute

The sessions-precomputation flag enables the attribution table and paths reader. Cold, ineligible, or failed job lookups fall back to live queries. Sessions that started before the one-day reachback or exceed the three-day writer scan budget read their dimensions live, while other sessions use the cache. These exceptions do not disable the cache for the entire query.

The writer excludes sessions longer than its scan budget. The reader also replaces dimensions of cached sessions that later grow beyond that budget, including growth after the report end. It first selects conservative candidates from raw timestamp rows, then checks their exact start/end after aggregation. This avoids holding aggregate state for ordinary sessions. It filters candidate IDs before merging entry properties and joins both dimension sources to current pageview identities. Session IDs and dimensions remain inside ClickHouse, so the SQL size does not grow with the exception count. Both raw-session reads retain the timestamp bounds used by live attribution. Sessions whose ID timestamp is more than three days before the extended attribution read window remain outside both lookups. Their source events remain stored. Expanding this coverage requires changing and validating live and cached attribution together.

The writer query change invalidates existing job hashes. Deploy both writer and reader before warming the new jobs; keep the reader flag off until the controlled rollout validates coverage and query cost.

`MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS` covers calendar display days in the project timezone.
The warmer starts at local midnight that many days before the run's local date, then subtracts the team's attribution lookback and one reachback day in UTC.
It warms through the end of that local day so reports that include today have complete UTC daily-window coverage.
For projects west of UTC, this can warm a UTC window before it starts.
A job computed before its window starts stops being eligible at that start, including for stale reads.
The reader falls back to live calculation until the window is refreshed after it starts, so the earlier snapshot cannot hide new sessions.
The reader uses the same calendar boundary to check its maximum range.
This includes the complete starting day for relative ranges such as `-90d`, even across daylight saving changes.
Query overrides that extend before that boundary remain ineligible.

Calendar alignment does not change the writer query or existing job hashes.
Run the updated warmer to populate missing daily windows at either end before testing the full display range.
Existing ready jobs remain reusable if they satisfy the freshness policy, and missing coverage still falls back to live calculation.
The allowlist, daily chunk size, and query execution limits are unchanged.

With the existing serve-stale flag, readers may use jobs expired within six hours and enqueue debounced revalidation. Only that task runs reader-initiated inserts; it takes no stale grace. Scheduled writers also require fresh jobs. Classifier expression changes and the explicit dictionary version change the shared job hash, requiring fresh materialization.

The reader caches session dimensions, then joins them to current pageview identities by `session_id_v7`. It resolves both touchpoints and conversions through `events.person_id`, so person merges, splits, and delayed identity mappings follow the same behavior as live attribution without rebuilding session jobs. The stored `person_id` is not used for attribution.

Materialized CTEs share the pageview identity scan between reach and credit, and share the conversion aggregation with the timestamp bounds. Event scans remain necessary for identity and conversions; cached dimensions avoid merging entry properties and classifying channels for ordinary sessions. A narrow timestamp scan and selective dimension lookup handle exceptional sessions. This uses the existing `web_sessions_dimensional_preaggregated` schema and does not require a migration.

Queries that override the session table version or v2 join mode fall back to live attribution when they differ from the writer. AUTO and v2 share the same session semantics. Custom channel rules can use cached dimensions when they match the writer's project rules, including rules that depend on the full entry URL. The writer classifies the channel before storing it and includes the rules in the job hash, so rule changes require fresh jobs. Queries with different rules, or disabled project-timezone conversion, use the live path. Identity and execution-only modifiers do not invalidate cached dimensions.

The shared job hash excludes `cookielessTrafficIsRegular` because the writer does not classify traffic types.
Different evaluations of that rollout flag in background workers and query workers do not require new session jobs.

For the cache-key transition, an old job with an unset `cookielessTrafficIsRegular` keeps the same key because serialization already omitted null values.
An old job with an explicit `true` or `false` has a different key and needs replacement before cached reads resume.
There is no compatibility lookup for those old keys.
Use the updated writer to prepare valid jobs for the full attribution read window before enabling cached reads.
Keep cached reads disabled until a read-only job lookup confirms complete, fresh coverage.
Missing coverage falls back to live calculation, so changing the key alone does not guarantee faster queries.

Live and cached pageview scans include the full final second of the selected date range, matching conversion filters. This also applies to explicit fractional date bounds and pageview conversion goals.
Attribution filters compare the event timestamp directly with the date bounds, using microsecond precision for the end of the range.
This avoids copying timestamp casts into session filters and preserves the shared raw-session timestamp definition.
If either date boundary falls within a repeated local hour at a daylight saving transition, the reader uses live attribution because conversion filters parse dates without a UTC offset.
Ranges that cross a transition can still use cached dimensions when both boundaries are unambiguous.
