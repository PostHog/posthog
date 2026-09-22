# Attribution session precompute

The sessions-precomputation flag enables the attribution table and paths reader. Cold, ineligible, failed, or unproven session coverage falls back to live queries. A sessions-only check rejects sessions that overlap the read window but started before its one-day reachback; longer custom session IDs cannot silently lose attribution.

`MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS` covers display days. The proposed warmer adds the team's attribution lookback and one reachback day: default 90 + 90 + 1 = 181 trailing days, previously 90. This approximately doubles initial daily chunks and retained job coverage; actual scan/storage cost depends on session volume and duration. The allowlist and environment values are unchanged. Evaluate this cost before rollout. Query overrides beyond the total warmed span remain ineligible.

With the existing serve-stale flag, readers may use jobs expired within six hours and enqueue debounced revalidation. Only that task runs reader-initiated inserts; it takes no stale grace. Scheduled writers also require fresh jobs. Classifier expression changes and the explicit dictionary version change the shared job hash, requiring fresh materialization.

The reader caches session dimensions, then joins them to current pageview identities by `session_id_v7`. It resolves both touchpoints and conversions through `events.person_id`, so person merges, splits, and delayed identity mappings follow the same behavior as live attribution without rebuilding session jobs. The stored `person_id` is not used for attribution.

Materialized CTEs share the pageview identity scan between reach and credit, and share the conversion aggregation with the timestamp bounds. Event scans remain necessary for identity and conversions; cached dimensions avoid the sessions join and channel classification. This uses the existing `web_sessions_dimensional_preaggregated` schema and does not require a migration.

Queries that override the session table version or v2 join mode fall back to live attribution when they differ from the writer. AUTO and v2 share the same session semantics. Custom channel rules on either the query or the team, and disabled project-timezone conversion, also use the live path. Identity and execution-only modifiers do not invalidate cached dimensions.

Live and cached pageview scans include the full final second of the selected date range, matching conversion filters. This also applies to explicit fractional date bounds and pageview conversion goals.
Attribution filters compare the event timestamp directly with the date bounds, using microsecond precision for the end of the range.
This avoids copying timestamp casts into session filters and preserves the shared raw-session timestamp definition.
If either date boundary falls within a repeated local hour at a daylight saving transition, the reader uses live attribution because conversion filters parse dates without a UTC offset.
Ranges that cross a transition can still use cached dimensions when both boundaries are unambiguous.
