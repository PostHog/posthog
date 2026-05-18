# Job Queue V2 Migration Plan (hogflow → postgres-v2)

**Date:** 2025-05-18
**Owner:** Myke
**Collaborators:** Dan Marchuk

## Context

- **EU:** 100% of hogflow traffic already on postgres-v2 (~3 weeks, stable)
- **US:** team2 is 100% on postgres-v2 (team2 accounts for ~90% of US v2 traffic, mostly rate-limiting workflow). All other US teams still on Kafka.
- **Scope:** Only the `hogflow` queue moves to v2. `hog` and `hogoverflow` stay on their current backends.
- The March 18-19 cross-routing incident (ghost runs, 4x duplicate actions) was caused by missing `CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING` on the hogflow postgres-v2 worker. Fixed in PR #51599.
- `HogFlowDuplicateObserverService` (PR #52776) is **observe-only** — it records a Prometheus metric (`hogflow_duplicate_invocation_detected_total`) when it detects a duplicate invocation but does **not** block execution. The `observe()` return value `{ duplicate: boolean }` is discarded by `observeDuplicateInvocation()` in `hogflow-executor.service.ts:159`.

**Goal:** Move all US hogflow traffic to postgres-v2, then strip away the Kafka write path for hogflow.

---

## 1. Risk Assessment

### 1.1 Known Risks (Mitigated)

| Risk                                                     | Mitigation                                                                                   | Status    |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------- | --------- |
| Cross-routing (source v2, produce to Kafka) → ghost runs | PR #51599 — `queueInvocationResults` now explicitly releases source jobs when target differs | **Fixed** |
| Missing producer mapping on new workers                  | Validated in charts config (#9167)                                                           | **Fixed** |
| Stalled/poisoned jobs undetected                         | Grafana alerts on v2 stalled + poisoned jobs (#9168)                                         | **Done**  |

### 1.2 Open Risks

| #   | Risk                                                                                                                                                                                                                                                                                                   | Severity | Likelihood | Notes                                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | **Silent data divergence on EU** — v2 may have subtle issues not visible in metrics that customers haven't reported. Rolling remaining US teams doubles the blast radius                                                                                                                               | High     | Low        | EU has been stable 3 weeks + team2 on US is stable. Mitigate with e2e canary workflows (Section 4)                                                        |
| R2  | **Postgres-v2 database capacity under full US load** — team2 alone is ~90% of current US v2 traffic, but that's mostly one workflow. Full rollout adds many more diverse workflows with different load patterns                                                                                        | Medium   | Medium     | Monitor `CYCLOTRON_NODE_MAX_CONNECTIONS` (default 10), check pg connection saturation. May need higher pool size for full US load                         |
| R3  | **Janitor stall timeout races** — Default `CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS=30s` with `maxTouchCount=3`. If a workflow action takes >30s (e.g., slow external API), the janitor resets it, causing re-execution. The duplicate observer is **observe-only** and will NOT block the re-execution | Medium   | Medium     | Consider whether to promote the observer to actually block duplicates, or increase stall timeout for hogflow                                              |
| R4  | **No active deduplication** — `HogFlowDuplicateObserverService` only emits a metric when it detects duplicates (`hogflow-executor.service.ts:159` discards the result). If the janitor creates ghost runs, there's no runtime prevention — only observability                                          | Medium   | Low        | Cross-routing root cause is fixed (PR #51599), so ghost runs from that vector shouldn't recur. Janitor-caused duplicates remain possible for slow actions |
| R5  | **Backpressure behavior difference** — Kafka has built-in consumer group rebalancing. Postgres-v2 uses `FOR UPDATE SKIP LOCKED` polling (50ms). Under load spikes, v2 may have different latency characteristics                                                                                       | Low      | Medium     | Monitor dequeue latency and queue depth during rollout                                                                                                    |
| R6  | **State serialization size** — Jobs store state as `BYTEA`. Large workflow states could hit postgres row size limits or cause OOM during bulk operations                                                                                                                                               | Low      | Low        | No current limit enforcement — add monitoring                                                                                                             |
| R7  | **Rollback complexity** — If v2 fails mid-rollout, in-flight v2 jobs need to complete or be migrated back. There's no v2→Kafka migration path                                                                                                                                                          | High     | Low        | Plan: let v2 jobs drain naturally, route new jobs to Kafka. Janitor handles stalled ones                                                                  |

---

## 2. Migration Strategy

**Scope: hogflow queue only.** `hog` and `hogoverflow` queues remain unchanged.

### Phase 1: Expand US hogflow to All Teams (1-2 days)

- [ ] Currently: team2 at 100% v2 via `CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING`
- [ ] Step 1: Route 10% of all US hogflow to v2
  - Config: `CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING` includes `hogflow:postgres-v2:0.1,hogflow:kafka:0.9`
  - Keep team2 override at 100% v2
- [ ] Step 2: 50% → `hogflow:postgres-v2:0.5,hogflow:kafka:0.5`
- [ ] Step 3: 100% → `hogflow:postgres-v2`
- [ ] Monitor between each step (minimum 2 hours per step):
  - Queue depth (Grafana dashboard `ddfj6r0xhgykg0c`)
  - Stalled job count
  - Poisoned job count
  - `hogflow_duplicate_invocation_detected_total` metric (observe-only, but spike = problem)
  - Cyclotron v2 DB connection pool utilization
  - Workflow execution success rate
- [ ] Run e2e canary workflows on team2 throughout (Section 4)

### Phase 2: Drain Kafka hogflow Consumer (1-2 days)

- [ ] Once all hogflow traffic routes to v2, monitor Kafka consumer lag for hogflow → 0
- [ ] Ensure the v2 hogflow consumer (`cdp-cyclotron-worker-hogflow` with `CONSUMER_MODE=postgres-v2`) is processing all traffic
- [ ] Once Kafka hogflow lag is 0 and stable, stop the Kafka hogflow consumer

### Phase 3: Strip Kafka Write Path for hogflow (after 1 week of stability)

- [ ] Remove Kafka as a valid producer target for the `hogflow` queue
- [ ] Remove cross-routing logic for hogflow (no more Kafka↔v2 for this queue)
- [ ] Clean up team-specific mapping overrides for hogflow (no longer needed when all teams are v2)
- [ ] Keep observe-only dedup — low cost, useful signal

### Rollback Plan

At any phase:

1. Revert hogflow producer mapping: `hogflow:kafka` (or restore team mapping)
2. Restart Kafka hogflow consumer
3. V2 in-flight jobs drain naturally via janitor (stall → reset → poison pill after 3 touches)
4. No active dedup blocking — monitor `hogflow_duplicate_invocation_detected_total` for any ghost run signal during rollback

---

## 3. Test Coverage Gaps

### 3.1 Critical Gap: No E2E Tests for postgres-v2 Mode

**File:** `nodejs/src/cdp/cdp-e2e.test.ts`

- Tests `describe.each(['postgres', 'kafka', 'hybrid'])` — **`postgres-v2` is NOT tested**
- This means the full pipeline (event → events-consumer → cyclotron producer → v2 worker → completion) has **zero integration test coverage**

**Action:** Add `'postgres-v2'` to the e2e test matrix. This requires:

- Setting `CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING = '*:postgres-v2'`
- Setting `CYCLOTRON_NODE_DATABASE_URL` in test config
- Starting a `CyclotronV2Worker` consumer alongside the events consumer
- Verifying the full invocation lifecycle

### 3.2 Cross-Backend Routing Integration Tests

**File:** `nodejs/src/cdp/services/job-queue/job-queue.test.ts`

- Has 28 references to `postgres-v2` but all use **mocked** queue backends
- No test actually creates a v2 job, routes it to Kafka, and verifies the v2 source is released

**Action:** Add integration tests (with real Postgres + Kafka) for:

- [ ] v2 source → Kafka target: verify v2 job is released after Kafka produce
- [ ] v2 source → v2 target (different queue): verify in-place update
- [ ] Kafka source → v2 target: verify new v2 job created + Kafka offset committed
- [ ] Job with `queueScheduledAt` far in future: verify routing to postgres when `forceScheduledToPostgres=true`

### 3.3 Janitor Interaction Tests

**File:** `nodejs/src/cdp/services/cyclotron-v2/cyclotron-v2.test.ts`

- Tests janitor in isolation but NOT concurrent with active workers

**Action:** Add tests for:

- [ ] Worker processing a job while janitor runs — verify janitor doesn't reset active jobs (heartbeat keeps them alive)
- [ ] Worker crashes mid-processing (no heartbeat) — verify janitor resets job
- [ ] Job exceeds `maxTouchCount` — verify it becomes poisoned and is NOT re-executed

### 3.4 State Size Boundary Tests

**Action:** Add tests for:

- [ ] Large workflow state (approaching 1 MiB) — verify serialization/deserialization
- [ ] State with special characters, unicode, binary data in BYTEA column

### 3.5 Consumer Drain Tests

**Action:** Add test for the Phase 3 scenario:

- [ ] Producer routes to v2, but Kafka consumer still has in-flight jobs
- [ ] Verify both consumers can run concurrently without double-processing
- [ ] Verify Kafka consumer eventually drains to 0

### 3.6 Priority & Scheduling Under V2

**Action:**

- [ ] Test that priority ordering is maintained under concurrent dequeue (`FOR UPDATE SKIP LOCKED` + `ORDER BY priority ASC, scheduled ASC`)
- [ ] Test scheduled jobs with v2 — verify they're not dequeued before their scheduled time

---

## 4. E2E Production Canary Workflows

### 4.1 Design

Create 2-3 synthetic workflows on team2 (US) that exercise key paths and can be used for alerting:

#### Workflow A: Simple Event → HTTP Destination

- **Trigger:** Custom event `$canary_simple` with property `canary=true`
- **Action:** HTTP POST to an internal endpoint (or a webhook.site-style receiver we control)
- **Expected:** Workflow completes within 5 seconds of event
- **Monitors:**
  - Time from event ingestion to workflow completion
  - HTTP response status code
  - No duplicate executions (check by unique canary ID in payload)

#### Workflow B: Event → Delay → HTTP Destination

- **Trigger:** Custom event `$canary_delayed` with property `canary=true`
- **Actions:**
  1. Delay 60 seconds
  2. HTTP POST with payload including original event UUID + delay start time
- **Expected:** HTTP fires exactly once, ~60 seconds after event
- **Monitors:**
  - Delay accuracy (should be 55-65 seconds)
  - Exactly 1 execution per trigger event
  - Job transitions: available → running → rescheduled (delay) → available → running → completed

#### Workflow C: Event → Conditional Branch → HTTP Destination

- **Trigger:** Custom event `$canary_branch` with property `branch` = "a" or "b"
- **Actions:**
  1. Conditional branch on `event.properties.branch`
  2. Branch A: HTTP POST to endpoint A
  3. Branch B: HTTP POST to endpoint B
- **Expected:** Correct branch fires based on event property
- **Monitors:**
  - Correct branch selected
  - Single execution per trigger

### 4.2 Implementation Approach

1. **Receiver endpoint:** Create a simple Cloud Function / Lambda that logs received payloads to a PostHog project (or ClickHouse table) with timestamps
2. **Cron trigger:** A scheduled job (GitHub Actions, or a PostHog batch workflow) sends `$canary_simple`, `$canary_delayed`, `$canary_branch` events to US team2 every 10 minutes
3. **Alerting:**
   - Query ClickHouse for canary completions: `SELECT count() FROM events WHERE event = '$canary_completed' AND team_id = 2 AND timestamp > now() - INTERVAL 30 MINUTE`
   - Alert if count drops below expected (e.g., <2 completions in 30 min when sending every 10 min)
   - Alert on duplicate canary completions (same trigger event UUID, multiple completion events)
   - Alert on latency: canary completion time - canary trigger time > threshold

### 4.3 Canary as Regression Detection

These canaries serve double duty:

- **During migration:** Validate v2 is working correctly on US team2 before expanding
- **After migration:** Permanent regression detection for the workflow pipeline
- **Future:** Can be templated for EU with minimal changes

---

## 5. Observability Checklist

Before starting Phase 1, verify these are in place:

- [ ] Grafana dashboard `ddfj6r0xhgykg0c` (Workflows postgres-v2 migration) is accessible and shows US data
- [ ] Alerts on v2 stalled jobs (#9168) are firing correctly (test by creating a synthetic stalled job)
- [ ] Alerts on v2 poisoned jobs are firing correctly
- [ ] `hogflow_duplicate_invocation_detected_total` Prometheus metric is being scraped
- [ ] Cyclotron v2 database connection pool metrics are visible
- [ ] Queue depth per queue_name is charted
- [ ] Worker dequeue latency (time from job available → job running) is charted

---

## 6. Open Questions

1. **Promote dedup to blocking?** The observer currently only emits metrics. Should we make it actually skip duplicate invocations (use the `{ duplicate }` return value in `hogflow-executor.service.ts`)? Low-cost safety net, but may mask bugs we'd rather detect via alerts.
2. **Postgres-v2 DB sizing for US:** What's the current connection pool config for US? Is `CYCLOTRON_NODE_MAX_CONNECTIONS=10` sufficient for full hogflow traffic?
3. **Scheduled job routing during transition:** `CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_FORCE_SCHEDULED_TO_POSTGRES` only kicks in when `target === 'kafka'` (`job-queue.ts:236`). During Phase 1 (partial Kafka routing), hogflow jobs that roll into the Kafka bucket AND have a future `scheduledAt` >10s would be rerouted to postgres v1 instead of v2. Once hogflow is 100% v2, this code path is dead. Not a blocker, but worth being aware of during the gradual rollout — some delayed hogflow jobs may briefly land on v1.
4. **Stall timeout for hogflow:** Default 30s may be too aggressive for workflow actions that call slow external APIs. Consider increasing `CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS` for hogflow, or ensuring heartbeat is sent during long-running actions.

---

## Session Log

- **2025-05-18:** Initial plan created. Researched current codebase state, identified test gaps, designed canary workflows.
- **2025-05-18:** Created `nodejs/src/cdp/workflows-e2e.test.ts` — 6 e2e tests exercising hogflows through postgres-v2:
  1. Simple workflow (trigger → function → exit)
  2. Delay workflow (trigger → delay → function → exit) — tests reschedule/state round-trip
  3. Conditional branch (trigger → branch → function A/B → exit)
  4. Workflow disabled mid-execution (archived during delay)
  5. Multiple workflows matching same event
  6. Fetch failure with retries
- Created `test_cyclotron_node` database locally and ran migrations.
- Tests follow same pattern as `cdp-e2e.test.ts` — only `fetch` is mocked, everything else is real. Need full dev infra (Kafka, Redis, Postgres) to run.
