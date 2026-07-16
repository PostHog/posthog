# Free organization query quota rollout plan

## Status

This is a design and rollout plan only.
It does not add an allowance, return HTTP 402, or change what customers can query.

The change is intentionally split into independently deployable stages.
Each stage must be observed and accepted before work starts on the next one.

## Goal

Limit the ClickHouse read cost created by free organizations without unexpectedly blocking valid customer queries.

The intended scope is:

- query-service calculations authenticated with a personal API key
- calculations required to render a public shared dashboard or insight

Session-authenticated product usage, OAuth requests, and paid-plan limits are out of scope.

## Existing architecture

PostHog already calculates `api_queries_read_bytes` from ClickHouse query logs and includes it in the periodic usage report sent to Billing.
Billing can return resource usage, limits, billing-period dates, and trust scores, and PostHog stores that data on the organization.

The existing quota Redis data is a decision cache, not a live usage ledger.
Quota tasks decide that an organization is limited from billing usage data, then write its team tokens to a Redis sorted set.
Request paths read that set to decide whether to allow work.

Billing does not currently define the proposed free-plan query allowance.
We should not add that allowance or rely on a limited-team Redis decision until we have a faster, observable usage signal that we trust.

## Safety principles

- Do not return HTTP 402 until the measured and would-limit stages have been reviewed.
- Use actual ClickHouse `read_bytes`, including bytes read by queries that fail during execution.
- Do not count validation failures that never start ClickHouse work.
- Attribute usage to the owning organization, including public shared dashboard and insight traffic.
- Keep personal API key eligibility restricted to query-service work.
- Do not charge for serving an existing cached result when no new ClickHouse work runs.
- Keep paid organizations out of the proposed free-plan decision.
- Fail open when usage storage or lookup is unavailable.
- Keep measurement active after enforcement so observed and blocked behavior remain comparable.
- Make enforcement removable through one environment setting without disabling measurement.

## Stage 1: Redis usage ledger

Add an organization-level Redis ledger for query read bytes.
This stage records usage only and has no allowance or query-path decision.

The ledger must:

- use actual finalized ClickHouse `read_bytes`
- include completed and execution-failed chargeable queries
- cover personal API key query-service traffic and sharing-token traffic
- aggregate across every team in an organization
- separate billing periods so a reset cannot mix old and new usage
- expire data after the period plus a recovery window
- update atomically
- avoid double counting retries, duplicate query-log rows, and distributed query entries
- tolerate delayed query-log data
- fail open without affecting query execution

Before implementation, choose and document the writer:

1. A query-completion writer can update Redis with low latency, but only if the execution boundary exposes authoritative read bytes and guarantees one update per ClickHouse query.
2. A query-log collector uses the billing source of truth, but needs an incremental watermark and idempotency strategy before it can safely increment Redis.

Do not infer bytes from the requested query or estimate them before execution.

### Stage 1 acceptance gate

- Redis totals reconcile with the existing usage-report totals over complete periods within an agreed tolerance.
- Retries, async execution, failed queries, shared resources, and cache hits have documented test cases.
- Redis failures do not fail customer queries.
- The key count, memory use, update rate, and expiry behavior are understood.

## Stage 2: PostHog measurement

Emit PostHog events from the ledger so the rollout can be evaluated with a PostHog dashboard.
Prometheus and logs can support operations, but they are not the primary product-impact measurement.

Prefer periodic organization snapshots over one analytics event per query.
The snapshot event should include:

- organization and team grouping information
- billing-period start and end
- accumulated read bytes
- measurement timestamp and source
- plan tier
- whether personal API key, shared-resource, or both kinds of traffic contributed
- reconciliation status against the existing usage report

If the snapshot is emitted from a Celery task, use `ph_scoped_capture` rather than `posthoganalytics.capture`.

Build a PostHog dashboard that shows:

- usage distribution for free organizations
- usage over time within a billing period
- personal API key and shared-resource contribution
- failed-query contribution
- organizations approaching candidate thresholds
- reconciliation differences and missing snapshots
- Redis write, read, and expiry failures

This stage still has no allowance and no would-limit decision.

### Stage 2 acceptance gate

- The dashboard has enough history to cover an agreed observation window, including billing-period boundaries.
- The measured population matches the intended free-organization scope.
- The team responsible for Billing agrees that the unit and period semantics can support a future allowance.
- Product, Billing, Query, Infrastructure, Support, and Customer Success owners agree on the candidate threshold and expected customer impact.

## Stage 3: Would-limit reporting

Add a candidate free-plan threshold without blocking queries.
The query path reads the Redis ledger and records when it would have returned HTTP 402, then continues normally.

Use one environment-controlled mode with explicit values:

- `off`: keep the ledger and usage snapshots, but do not make query-path decisions
- `observe`: record would-limit decisions and allow the query
- `enforce`: record the same decision and return HTTP 402

The setting should default to `off` until this stage and to `observe` when would-limit reporting is intentionally enabled.

Capture a PostHog decision event when a query is over the candidate threshold.
It should include:

- `decision_mode` as `observe` or `enforce`
- access method
- organization and team grouping information
- accumulated bytes and candidate threshold
- billing-period end
- query type
- shared dashboard or insight identifiers when applicable
- a client query identifier for deduplication

Async requests can reach the query runner more than once.
The event contract must define which boundary emits the decision or how the dashboard deduplicates it.

### Stage 3 acceptance gate

- No request returns HTTP 402 in `observe` mode.
- The PostHog dashboard shows distinct affected organizations and queries, not only event volume.
- Paid organizations do not appear in would-limit decisions.
- Shared dashboard and insight impact is reviewed separately from personal API key impact.
- Support and customer-facing copy have been reviewed against real would-limit examples.
- The candidate threshold and expected reporting lag are accepted by the rollout owners.

## Stage 4: Enforcement

Enable `enforce` only after the would-limit gate is complete.

When a free organization is over the threshold:

- allow an existing cached result that requires no new ClickHouse work
- prevent new eligible ClickHouse work from starting
- return HTTP 402 with a stable error code and the billing-period reset time when available
- keep emitting the same PostHog decision event with `decision_mode="enforce"`
- include public shared dashboard and insight calculations

Changing the environment mode from `enforce` to `observe` or `off` must stop new HTTP 402 responses after the affected processes restart or redeploy.
The Redis ledger and PostHog usage snapshots must continue so the incident can be compared with previous behavior.

### Stage 4 acceptance gate

- Enforcement has been tested for blocking, async, shared-resource, failed-query, and fresh-cache paths.
- Customer pricing and API documentation state the allowance, reset semantics, and shared-resource behavior.
- Support has the error contract, dashboard, kill-switch instructions, and escalation owner.
- Alerts cover paid-plan decisions, Redis failures, unexpected retry volume, and a material difference from would-limit forecasts.
- The rollout begins with a limited exposure and has a named go or no-go owner.

## Delivery sequence

Use separate pull requests so each stage can deploy and be reviewed independently:

1. Agree on this plan and the Redis ledger design.
2. Implement the Redis ledger without query-path decisions.
3. Add PostHog snapshots and build the measurement dashboard.
4. Add `observe` mode and review would-limit impact.
5. Add the HTTP 402 contract and enable `enforce` only after the rollout gates pass.

Do not combine the Redis ledger, candidate threshold, would-limit reporting, and enforcement in one release.

## Open decisions

- Where authoritative per-query read bytes should be written to Redis
- The idempotency key and reconciliation strategy
- The billing-period source when local billing metadata is missing or stale
- The Redis key shape, expiry window, and memory budget
- Snapshot cadence and PostHog event schema
- Candidate threshold and whether it is one value for every free organization
- Treatment of trust scores, `never_drop_data`, and existing quota-retention flags
- Whether stale cached results should remain available after enforcement
- Ownership of the dashboard, alerts, customer communication, and emergency rollback

## Customer communication

Do not announce a limit during the ledger or measurement stages because customer behavior does not change.

Before enforcement, explain in plain language:

- which API and shared-resource queries count
- that the allowance is based on data read, not request count
- when usage resets
- what remains available after the allowance is reached
- how organization admins can see usage and change plans
- that HTTP 402 is not a temporary concurrency error and should not be retried repeatedly
