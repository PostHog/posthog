# Attribution session precompute

The sessions-precomputation flag enables the attribution table and paths reader. Cold, ineligible, failed, or unproven session coverage falls back to live queries. A sessions-only check rejects sessions that overlap the read window but started before its one-day reachback; longer custom session IDs cannot silently lose attribution.

`MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS` covers display days. The proposed warmer adds the team's attribution lookback and one reachback day: default 90 + 90 + 1 = 181 trailing days, previously 90. This approximately doubles initial daily chunks and retained job coverage; actual scan/storage cost depends on session volume and duration. The allowlist and environment values are unchanged. Evaluate this cost before rollout. Query overrides beyond the total warmed span remain ineligible.

With the existing serve-stale flag, readers may use jobs expired within six hours and enqueue debounced revalidation. Only that task runs reader-initiated inserts; it takes no stale grace. Scheduled writers also require fresh jobs. Classifier expression changes and the explicit dictionary version change the shared job hash, requiring fresh materialization.

The converter join now reads only identity and timestamp bounds; two event scans remain. Stored person identities can still disagree with live conversions after person merges until recomputation.
