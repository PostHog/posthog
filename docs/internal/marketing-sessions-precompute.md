# Marketing session precompute writer

The writer partitions sessions by the UTC hour of their start. It stores the first and last pageview timestamps, even when a session extends beyond the next day. The event scan ends at the latest observed session end for sessions starting in the requested window; non-pageview events do not extend the stored pageview bounds.

Results are snapshots subject to the configured freshness schedule. The one-day settling period controls cache freshness, not a maximum supported session duration.

## Deployment configuration

Before enabling this writer, wire these environment variables through the deployment configuration in `PostHog/charts` and `PostHog/secrets`:

| Variable | Consumers | Default | Operational meaning |
| --- | --- | --- | --- |
| `MARKETING_SESSIONS_PRECOMPUTE_TEAM_IDS` | Dagster code location running the marketing session job | Built-in cloud allowlist; empty on self-hosted | Comma-separated team IDs. An explicitly empty value disables writes. |
| `MARKETING_SESSIONS_PRECOMPUTE_WINDOW_DAYS` | Dagster writer and every process importing the shared coverage setting | `90` | Trailing coverage in days. Keep writer and reader deployments consistent. |

Deploy the table migration before running the job. Verify the effective variables in each target deployment, including that an empty allowlist produces a no-op. A definition in this repository alone does not wire deployment variables; changes and verification in the deployment repositories are a rollout prerequisite.
