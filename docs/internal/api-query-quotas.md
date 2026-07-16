# API and shared query quotas

## Purpose

Query quotas limit the ClickHouse read cost created by personal API key requests and public shared dashboard or insight views.
The first rollout is configured for free organizations only.
Application code remains plan-agnostic so an existing finite allowance on another plan continues to work, but this change does not add or lower a paid-plan allowance.

The quota is a cost control, not a concurrency control.
Concurrency limits protect the service from simultaneous work and return HTTP 429.
Query quotas protect billing-period usage and return HTTP 402.

## Responsibilities

- Billing defines the allowance for each plan and sends usage, limit, billing-period, and trust-score data to PostHog.
- The usage-report pipeline measures chargeable ClickHouse reads and reports them per team for the billing period.
- The billing quota task decides which organizations are limited and writes their team tokens to Redis with the billing-period end as the expiry.
- The query layer checks the Redis decision before starting new ClickHouse work and returns the customer-facing quota response.
- The launch owner coordinates pricing documentation, support guidance, customer communication, dashboards, and alerting before enabling a finite free-plan allowance.

## Metering

The resource key is `api_queries_read_bytes`.
Usage is the sum of ClickHouse `read_bytes` for query-log rows tagged `chargeable`.
Personal API key calculations and shared dashboard or insight calculations set that tag.

Failed queries count when ClickHouse reports bytes read.
Validation failures that do not start execution contribute no meaningful read bytes.
The aggregation intentionally does not filter to successful `QueryFinish` rows.

The usage report and quota decision are asynchronous.
A newly over-limit organization can continue querying until the next quota update reaches Redis.
The query path uses the existing 30-second process cache for Redis quota membership.

## Rollout mode and kill switch

`QUERY_QUOTA_ENFORCEMENT_ENABLED` controls whether a limited query is blocked.
It defaults to `false` so the first release is dry-run only:

- `false`: check the Redis quota decision, emit the would-block metric and structured log, then allow the query to continue.
- `true`: emit the same observability signals and return HTTP 402 before new ClickHouse work starts.

Set the variable consistently on web and async query-worker processes.
Changing it requires the affected processes to restart or redeploy.
Setting it back to `false` is the operational kill switch if enforcement produces unexpected customer impact; metering and dry-run observability continue while 402 responses stop.

Dry-run decisions emit `posthog_external_query_quota_decision_total` with `plan_tier`, `access_method`, and `enforcement_mode="dry_run"` labels.
The `query_quota_decision` structured log includes team, organization, client query, query type, dashboard or insight identifiers, access method, plan tier, enforcement mode, and billing-period end.
Use the counter for aggregate rates and the logs for organization-level investigation without adding high-cardinality Prometheus labels.
Async requests can produce decisions when they are enqueued and when a worker picks them up; use the client query identifier when deduplicating logs for request-level analysis.

## Enforcement timing decision

The first version is intentionally an eventual billing-period limit, not a real-time hard cap.
The usage-report pipeline, billing quota task, and Redis decision cache remain the authoritative enforcement loop.
A request that crosses the allowance is allowed to finish, and later requests can continue until that loop marks the organization as limited.
Once the decision is visible to the query process and enforcement is enabled, new uncached personal API key queries and shared dashboard or insight refreshes return HTTP 402.

This delay is an accepted simplicity tradeoff for the first rollout.
The query path will not maintain a second per-query byte accumulator or synchronously fetch current billing usage.
Avoiding those mechanisms keeps one source of truth, removes a write or remote lookup from every query, and avoids reconciliation between live estimates and finalized ClickHouse usage.
Observed usage beyond the allowance should be monitored to validate the reporting interval, but the existence of reporting lag does not by itself block launch.

## Request scope

The first rollout covers requests to the query API authenticated with a personal API key and query calculations made while rendering shared dashboards or insights.
Session-authenticated product usage, OAuth requests, and other in-app queries are not included.
Materialized endpoints have separate concurrency controls but remain chargeable when run through the personal API key query service.
For personal API keys, the query runner must also be explicitly marked as query-service work; authentication method alone does not make an in-app or unrelated endpoint quota eligible.
Sharing-token renders are the deliberate exception because shared resources create external query work without using the query-service flag.

Shared traffic is attributed to the organization that owns the shared resource.
Anonymous viewers do not receive a separate allowance, and rotating a sharing token does not reset usage.

The quota check applies only when a request would start new ClickHouse work:

| Request state                                    | Result while limited                         |
| ------------------------------------------------ | -------------------------------------------- |
| Fresh cached API or shared result                | Return the cached result                     |
| Stale or missing cache with blocking calculation | HTTP 402                                     |
| A request that would enqueue async calculation   | HTTP 402 without enqueueing work             |
| Session or OAuth in-app calculation              | Existing behavior; this quota does not apply |

This distinction keeps no-cost cache reads available while preventing new billable reads.
Quota activation does not cancel a query that is already running or an async task that was enqueued before the organization became limited.

Shared dashboards can therefore remain available from cache after the organization becomes limited.
Once a tile needs new ClickHouse work, the shared dashboard or insight request returns HTTP 402 instead of refreshing the tile.

## Customer response contract

When enforcement is enabled, the query API and shared dashboard or insight endpoints return HTTP 402 with a stable error type and code:

```json
{
  "type": "quota_limited",
  "code": "quota_limit_exceeded",
  "detail": "Your organization has reached its query usage limit for this billing period. New API queries and shared dashboard or insight refreshes are unavailable. Ask an organization admin to review Billing settings, or try again after the billing period resets.",
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
- `never_drop_data` bypasses query limiting because this resource is not in `GRACE_PERIOD_EXEMPT_RESOURCES`.
- The `retain-data-past-quota-limit` feature flag can bypass a new limit before the organization is already limited.

These behaviors must be reviewed explicitly for the free-plan rollout because they can extend access beyond the normal reporting delay.

## Reliability and operations

The query path reuses the existing Redis quota decision cache rather than maintaining a live usage counter.
This is the chosen enforcement model, not a fallback for the first rollout.
It keeps the billing usage report authoritative and avoids adding a request-time dependency on billing or a write on every query.
Enforcement therefore depends on the existing usage-report schedule, billing quota task, Redis quota infrastructure, and query-process cache.

Quota membership is keyed by the team's project token, not the caller's personal API key or sharing token.
Rotating a project token can delay enforcement until the quota task refreshes Redis.
The organization usage record remains the source for billing-period reset metadata.

Monitor at least:

- HTTP 402 responses from query and shared-resource endpoints
- `posthog_external_query_quota_decision_total` split by plan tier, access method, and enforcement mode
- distinct organizations and teams in `query_quota_decision` logs, with an alert if paid or enterprise organizations appear unexpectedly
- organizations entering and leaving `api_queries_read_bytes` quota limiting
- usage beyond the configured allowance before enforcement
- Redis quota lookup failures
- repeated client retries after HTTP 402

## Rollout checklist

1. Confirm the free-plan allowance and verify paid-plan configuration is unchanged.
2. Decide whether trust-score grace, `never_drop_data`, and the retention feature flag are acceptable for this resource.
3. Verify `API_QUERIES_ENABLED` in every cloud region.
4. Deploy with `QUERY_QUOTA_ENFORCEMENT_ENABLED=false` on web and async query workers.
5. Build the dry-run dashboard from `posthog_external_query_quota_decision_total` and `query_quota_decision` logs.
6. Review would-block rates, affected organizations, access-method mix, reporting lag, and any unexpected paid-plan decisions.
7. Test blocking and async personal API key and sharing-token requests with enforcement enabled in a non-production environment.
8. Test that fresh cached API and shared results remain available and no async task is enqueued while enforced.
9. Publish that shared dashboard and insight traffic consumes the allowance and can return HTTP 402 after it is exhausted.
10. Publish the allowance and eventual enforcement timing in customer API and pricing documentation.
11. Give Support the response shape, shared-dashboard behavior, reset behavior, expected enforcement delay, kill switch, and escalation path.
12. Enable enforcement gradually, monitor blocked decisions, and set `QUERY_QUOTA_ENFORCEMENT_ENABLED=false` immediately if impact differs materially from dry-run observations.

## Out of scope

- A limit for session-authenticated or OAuth queries
- A live Redis byte counter updated after each query
- CPU-based accounting
- Per-query byte ceilings
- New paid-plan limits

A later version can widen the meter to other customer-initiated query paths.
A reconciled live counter should only be considered if observed usage beyond the allowance materially undermines the cost-control goal.
