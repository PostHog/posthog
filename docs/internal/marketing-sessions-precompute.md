# Marketing session precompute writer

The writer partitions sessions by the UTC hour of their start in `web_sessions_dimensional_preaggregated`.
Window membership uses the exact start timestamp; hourly buckets are rounded explicitly in UTC, including for projects with half-hour or quarter-hour timezone offsets.
It writes `session_id_v7` as the numeric UUID representation from `events.$session_id_uuid` and stores the first and last pageview timestamps.
Each insert covers at most one day of session starts and scans events through three days after that window ends.
Before writing or accepting cached jobs, it checks the corresponding daily windows for sessions longer than three days.
If it finds one, it returns `ready=False` so the reader can use live attribution without truncating that session.
A failed coverage query also returns `ready=False`; an empty result accompanied by an error does not prove coverage.
Sessions lasting more than one day, including 49-hour sessions, remain supported by the cache.

Results are snapshots subject to the configured freshness schedule.
A start-day window settles three days after it ends, matching the maximum supported session duration.
Snapshots computed before that point expire at the settling boundary even when their stored TTL is longer, so a later first pageview cannot leave the window empty for 90 days.
Before settlement, the normal freshness schedule still applies; session dimensions are not updated on every event.
The writer respects the team's session table version: v3 when configured, otherwise v2; v1 requests fall back to live attribution.
Resolved query modifiers are part of the cache identity, so different source versions and channel rules cannot reuse the same jobs.

Stored person IDs are snapshots too: a merge after materialization can leave a touchpoint under its previous person ID until refresh.
The reader must resolve current identity before enabling this path for merged-person attribution.

## Deployment configuration

Before enabling this writer, wire these environment variables through the deployment configuration in `PostHog/charts` and `PostHog/secrets`:

| Variable                                    | Consumers                                                              | Default                   | Operational meaning                                                                                                                             |
| ------------------------------------------- | ---------------------------------------------------------------------- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `MARKETING_SESSIONS_PRECOMPUTE_TEAM_IDS`    | Dagster code location running the marketing session job                | Empty in every deployment | Comma-separated team IDs. An unset or explicitly empty value disables writes.                                                                   |
| `MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS` | Dagster writer and every process importing the shared coverage setting | `90`                      | Display history in days. Add team attribution lookback and one session reachback day; the defaults cover 181 days. Keep deployments consistent. |

Deploy the table migration before running the job. Verify the effective variables in each target deployment, including that an empty allowlist produces a no-op. A definition in this repository alone does not wire deployment variables; changes and verification in the deployment repositories are a rollout prerequisite.

The `marketing_sessions_precompute_chunk_done_total` and `marketing_sessions_precompute_chunk_failed_total` metrics count daily chunks.
Job metadata reports the number of teams and failed chunks separately.
