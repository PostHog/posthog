# Session replay API rate limits

The session recording API applies several rate limits at once, and the tightest ones are not the general API limits.
This page records what actually binds a caller, because "raise my session recording API limit" tickets usually name the wrong number.

## What binds a request

Every limit on this page applies only to a request that carries a personal API key.
The throttle classes all extend `PersonalApiKeyRateThrottle`, which lets an authenticated request through when it carries no personal API key.
App traffic is session-authenticated, so it meets none of these limits.
That is the usual reason a script with a personal API key gets a 429 while the same account's browser traffic does not.

A personal API key request to `/api/projects/:team_id/session_recordings` or its `snapshots` action passes through the general ClickHouse throttles.
On the list and `snapshots` actions a tier-aware replay throttle applies on top, and that is almost always the ceiling that blocks the caller.
The `/api/environments/:id/session_recordings` form meets the same limits, because `EnvironmentsRewriteMiddleware` rewrites it to the projects route, but that prefix is deprecated and its responses carry `Deprecation` and `Sunset` headers.

Sharing-token requests are the exception.
They get one per-token cap that replaces the general ClickHouse throttles instead of stacking on top of them.

| Limit | Applies to | Burst | Sustained |
| --- | --- | --- | --- |
| `clickhouse_burst` / `clickhouse_sustained` | Personal API key, every action | 240/minute | 1200/hour |
| `listing_*` (recording list) | Personal API key, free plan | 12/minute | 60/hour |
| `listing_*` (recording list) | Personal API key, paid plan | 60/minute | 300/hour |
| `listing_*` (recording list) | Personal API key, enterprise plan | 100/minute | 400/hour |
| `snapshots_*` | Personal API key, free plan | 12/minute | 60/hour |
| `snapshots_*` | Personal API key, paid plan | 60/minute | 300/hour |
| `snapshots_*` | Personal API key, enterprise plan | 100/minute | 400/hour |
| `replay_sharing_token` | Sharing-token requests, per token, instead of the limits above | 600/minute | none |

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
Two instance-level levers exist, and neither raises a ceiling:

- `RATE_LIMITING_ALLOW_LIST_TEAMS` skips throttling for the teams it names.
- `RATE_LIMIT_ENABLED` turns off every limit on this page for the whole deployment.
  Each throttle reads it through `is_rate_limit_enabled`, and it defaults to off, so a deployment that never set it applies none of these limits.

For bulk retrieval, point the customer at batch exports rather than a higher request rate.

## Observability

Throttle rejections land in metrics, not in PostHog events:

- `rate_limit_exceeded_total{scope,team_id,route}`, where `scope` carries the tier suffix, for example `snapshots_sustained_paid`.
  Prometheus only.
- `session_recording_api_throttled_total{location,auth_type}`, emitted by the sharing-token throttle, the dashboard listing helper, and the ClickHouse capacity and timeout paths on the list action.
  Prometheus, and also the PostHog Metrics product on deployments that set `OTEL_METRICS_EXPORT_URL` and `OTEL_METRICS_EXPORT_TOKEN`.

There is no way to query 429 volume per team from product data.
