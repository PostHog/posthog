# Session replay API rate limits

The session recording API applies several rate limits at once, and the tightest ones are not the general API limits.
This page records what actually binds a caller, because "raise my session recording API limit" tickets usually name the wrong number.

## What binds a request

Every request to `/api/environments/:id/session_recordings` and its `snapshots` action passes through the general ClickHouse throttles.
Personal API key requests pass through a tier-aware replay throttle on top, and that is almost always the ceiling that blocks them.

| Limit | Applies to | Burst | Sustained |
| --- | --- | --- | --- |
| `clickhouse_burst` / `clickhouse_sustained` | All requests to the viewset | 240/minute | 1200/hour |
| `listing_*` (recording list) | Personal API key, free plan | 12/minute | 60/hour |
| `listing_*` (recording list) | Personal API key, paid plan | 60/minute | 300/hour |
| `listing_*` (recording list) | Personal API key, enterprise plan | 100/minute | 400/hour |
| `snapshots_*` | Personal API key, free plan | 12/minute | 60/hour |
| `snapshots_*` | Personal API key, paid plan | 60/minute | 300/hour |
| `snapshots_*` | Personal API key, enterprise plan | 100/minute | 400/hour |
| `replay_sharing_token` | Sharing-token requests, per token | 600/minute | none |

The tier comes from `Organization.get_plan_tier()`, cached for 12 hours per team.
A tier the rate table does not name resolves to `free`.

Fetching the contents of one recording costs at least two `snapshots` calls: one to list the sources, then one per source.
So the sustained snapshot ceiling caps an enterprise caller at roughly 200 recordings per hour, not 400.

## Where the pieces live

- Rate values: `posthog/settings/session_replay.py` (`SNAPSHOT_RATE_*`, `LISTING_RATE_*`, `REPLAY_SHARING_TOKEN_RATE`). All are env-overridable per deployment, so the table above is the default, not a guarantee.
- Throttle classes and the tier lookup: `posthog/session_recordings/session_recording_api.py`.
- General ClickHouse throttles: `posthog/rate_limit.py`.

## What a 429 says

`SessionRecordingViewSet.check_throttles` names the limit that blocked the request, so a caller can tell which ceiling it hit:

```text
Rate limit exceeded. Recording snapshot requests are limited to 300 per hour on the paid plan. Expected available in 41 seconds.
```

When several throttles block the same request, the one with the longest wait is reported.
Reporting a shorter wait would send the caller back for another 429.
The response also carries `Retry-After`.

The recording list widget on a dashboard reports the same message through `get_replay_listing_throttle_error` instead of a 429, because one blocked tile must not fail the whole widget batch.

## Raising a limit

There is no per-team replay override.
`Team.api_query_rate_limit` looks like one but `load_team_rate_limit` only reads it for the HogQL query scope, so it has no effect here.
The only instance-level lever is `RATE_LIMITING_ALLOW_LIST_TEAMS`, which skips throttling altogether rather than raising a ceiling.

For bulk retrieval, point the customer at batch exports rather than a higher request rate.

## Observability

Throttle rejections are Prometheus only, not PostHog events:

- `rate_limit_exceeded_total{scope,team_id,route}`, where `scope` carries the tier suffix, for example `snapshots_sustained_paid`.
- `session_recording_api_throttled_total{location,auth_type}`, emitted by the sharing-token throttle, the dashboard listing helper, and the ClickHouse capacity and timeout paths on the list action.

There is no way to query 429 volume per team from product data.
