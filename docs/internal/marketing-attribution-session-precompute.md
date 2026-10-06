# Attribution session resolution

The `marketing-analytics-live-session-resolution` flag enables shared live session resolution for attribution tables and paths.
Eligible queries read current events and raw sessions without a Marketing session precompute job.
The sessions-precomputation reader is retired.
Marketing attribution no longer reads `web_sessions_dimensional_preaggregated` or queues session-cache refreshes.
The independent writer, Dagster job and schedule definitions, table, and schema remain in place.

## Query behavior

A materialized CTE selects pageview session IDs and current person IDs once per query.
The raw-session lookup filters to those IDs before merging entry properties and classifying channels.
Reach and credit share the resolved session rows and conversion aggregation within the query.
Table and paths reports execute separate queries.

Touchpoints and conversions resolve identity through `events.person_id`, so merges, splits, and delayed identity mappings follow the legacy live query without rebuilding session jobs.
Late-arriving events and session updates do not depend on a stored dimension snapshot.
Missing precompute coverage at a calendar boundary cannot switch this route back to the legacy query.
The report's date range and project timezone remain unchanged.

Eligible queries use 16 ClickHouse threads and aggregation in storage order where the grouping keys permit it.
The spill threshold and timeout stay unchanged.
These settings limit partial aggregation states and temporary spill files; they do not guarantee that every query will be faster.

## Eligibility and fallback

The shared route retains its existing eligibility checks.
It falls back to legacy live attribution for non-integer timezone offsets, ambiguous date boundaries, property access rules, test-account filters, incompatible session modifiers, or ranges beyond its configured limit.
Conversion goals that depend on session fields or deferred action expressions also use legacy attribution, preserving its wider session-ID lookup window.
Custom channel rules can use shared resolution when they match the project's rules.
AUTO and v2 have the same session semantics.

Raw-session lookups retain the legacy path's session-ID timestamp bounds, including its three-day buffer.
This does not extend coverage for older session IDs or guarantee that independently replicated events and sessions arrive together.
Pageview scans include the full final second of the selected range, matching conversion filters, including explicit fractional bounds.

`MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS` retains its existing name and default of `90` for configuration compatibility.
It limits the display history eligible for shared live resolution and still configures the independent writer's coverage.
The lower limit starts at project-local midnight that many calendar days before the end date, then subtracts the project's attribution lookback in UTC.
Query lookback overrides that extend before that limit remain ineligible.

## Rollout and rollback

The flag remains independent of other Marketing precomputation flags.
Attribution result cache keys distinguish its enabled and disabled states.
The query telemetry property `live_session_resolution_used` identifies the shared route.
Disabling the flag uses legacy live attribution.
Cost and conversion precomputation remain unchanged.

Validate result parity and query cost before extending the rollout.
A session backfill, session writer schedule, and session-cache TTL changes are not required.
See [Session precompute writer](marketing-sessions-precompute.md) for the independent writer's deployment configuration.
