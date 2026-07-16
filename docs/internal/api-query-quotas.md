# API query quotas

## Purpose

API query quotas limit the ClickHouse read cost created by personal API key requests to the query API.
The first rollout is configured for free organizations only.
Application code remains plan-agnostic so an existing finite allowance on another plan continues to work, but this change does not add or lower a paid-plan allowance.

The quota is a cost control, not a concurrency control.
Concurrency limits protect the service from simultaneous work and return HTTP 429.
API query quotas protect billing-period usage and return HTTP 402.

## Responsibilities

- Billing defines the allowance for each plan and sends usage, limit, billing-period, and trust-score data to PostHog.
- The usage-report pipeline measures chargeable ClickHouse reads and reports them per team for the billing period.
- The billing quota task decides which organizations are limited and writes their team tokens to Redis with the billing-period end as the expiry.
- The query API checks the Redis decision before starting new ClickHouse work and returns the customer-facing quota response.
- The launch owner coordinates pricing documentation, support guidance, customer communication, dashboards, and alerting before enabling a finite free-plan allowance.

## Metering

The resource key is `api_queries_read_bytes`.
Usage is the sum of ClickHouse `read_bytes` for query-log rows tagged `chargeable`.
Personal API key query-service calculations set that tag.

Failed queries count when ClickHouse reports bytes read.
Validation failures that do not start execution contribute no meaningful read bytes.
The aggregation intentionally does not filter to successful `QueryFinish` rows.

The usage report and quota decision are asynchronous.
A newly over-limit organization can continue querying until the next quota update reaches Redis.
The query path uses the existing 30-second process cache for Redis quota membership.

## Enforcement timing decision

The first version is intentionally an eventual billing-period limit, not a real-time hard cap.
The usage-report pipeline, billing quota task, and Redis decision cache remain the authoritative enforcement loop.
A request that crosses the allowance is allowed to finish, and later requests can continue until that loop marks the organization as limited.
Once the decision is visible to the query process, new uncached personal API key queries return HTTP 402.

This delay is an accepted simplicity tradeoff for the first rollout.
The query path will not maintain a second per-query byte accumulator or synchronously fetch current billing usage.
Avoiding those mechanisms keeps one source of truth, removes a write or remote lookup from every query, and avoids reconciliation between live estimates and finalized ClickHouse usage.
Observed usage beyond the allowance should be monitored to validate the reporting interval, but the existence of reporting lag does not by itself block launch.

## Request scope

The first rollout covers requests to the query API authenticated with a personal API key.
Session-authenticated product usage, OAuth requests, sharing tokens, and in-app queries are not included.
Materialized endpoints have separate concurrency controls but remain chargeable when run through the personal API key query service.

The quota check applies only when a request would start new ClickHouse work:

| Request state                                    | Result while limited                         |
| ------------------------------------------------ | -------------------------------------------- |
| Fresh cached result                              | Return the cached result                     |
| Stale or missing cache with blocking calculation | HTTP 402                                     |
| A request that would enqueue async calculation   | HTTP 402 without enqueueing work             |
| In-app calculation                               | Existing behavior; this quota does not apply |

This distinction keeps no-cost cache reads available while preventing new billable reads.
Quota activation does not cancel a query that is already running or an async task that was enqueued before the organization became limited.

## Customer API contract

The query API returns HTTP 402 with a stable error type and code:

```json
{
  "type": "quota_limited",
  "code": "quota_limit_exceeded",
  "detail": "Your organization has reached its API query usage limit for this billing period. Ask an organization admin to review Billing settings. You can try again after the billing period resets.",
  "attr": null,
  "extra": {
    "billing_period_end": "2026-08-01T00:00:00+00:00"
  }
}
```

`extra.billing_period_end` is omitted when billing-period metadata is unavailable.
Clients should branch on `code`, not the human-readable detail.
HTTP 429 remains reserved for temporary concurrency limits and callers can retry it after backoff.
HTTP 402 should not be retried repeatedly before the billing period resets or an organization admin changes the plan or limit.

## Billing configuration requirements

The free-only boundary is owned by billing configuration.
Before launch, confirm that the free plan has the intended finite `api_queries_read_bytes` allowance and that paid plans are unchanged unless they already define an allowance.

Separate from the accepted reporting delay, the existing quota framework can add grace or bypass enforcement:

- Customer trust scores can add a grace period before hard limiting.
- `never_drop_data` bypasses API query limiting because API queries are not in `GRACE_PERIOD_EXEMPT_RESOURCES`.
- The `retain-data-past-quota-limit` feature flag can bypass a new limit before the organization is already limited.

These behaviors must be reviewed explicitly for the free-plan rollout because they can extend access beyond the normal reporting delay.

## Reliability and operations

The query path reuses the existing Redis quota decision cache rather than maintaining a live usage counter.
This is the chosen enforcement model, not a fallback for the first rollout.
It keeps the billing usage report authoritative and avoids adding a request-time dependency on billing or a write on every query.
Enforcement therefore depends on the existing usage-report schedule, billing quota task, Redis quota infrastructure, and query-process cache.

Quota membership is keyed by the team's project token, not the caller's personal API key.
Rotating a project token can delay enforcement until the quota task refreshes Redis.
The organization usage record remains the source for billing-period reset metadata.

Monitor at least:

- HTTP 402 responses from the query endpoint
- `posthog_api_query_quota_limited_total` split by plan tier, with an alert if paid or enterprise organizations appear unexpectedly
- organizations entering and leaving `api_queries_read_bytes` quota limiting
- usage beyond the configured allowance before enforcement
- Redis quota lookup failures
- repeated client retries after HTTP 402

## Rollout checklist

1. Confirm the free-plan allowance and verify paid-plan configuration is unchanged.
2. Decide whether trust-score grace, `never_drop_data`, and the retention feature flag are acceptable for this resource.
3. Verify `API_QUERIES_ENABLED` in every cloud region.
4. Test blocking and async personal API key requests against a limited organization.
5. Test that fresh cached results remain available and no async task is enqueued while limited.
6. Publish the allowance, eventual enforcement timing, and HTTP 402 behavior in customer API and pricing documentation.
7. Give Support the response shape, reset behavior, expected enforcement delay, and escalation path.
8. Enable monitoring before rollout, alert on unexpected paid-plan blocks, and review usage leakage caused by the reporting interval.

## Out of scope

- A limit for in-app or sharing-token queries
- A live Redis byte counter updated after each query
- CPU-based accounting
- Per-query byte ceilings
- New paid-plan limits

A later version can widen the meter to other customer-initiated query paths.
A reconciled live counter should only be considered if observed usage beyond the allowance materially undermines the cost-control goal.
