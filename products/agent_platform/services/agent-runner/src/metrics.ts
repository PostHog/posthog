/**
 * Prometheus metrics for the agent-runner (the queue worker).
 *
 * Declared against the shared registry (`@posthog/agent-shared`'s
 * `runtime/metrics.ts`). The runner is the heart of the fleet — it's the only
 * service that actually drives sessions — so these cover its real failure
 * modes: queue-claim faults, concurrency saturation, per-stage session
 * failures, and the two external round-trips most likely to wedge a session
 * (sandbox acquire + MCP open). See worker.ts for the wiring.
 */

import { Counter, Gauge, Histogram } from '@posthog/agent-shared'

/**
 * Every terminal result of a `runOne()` run, by outcome. The complete
 * denominator for runner throughput + the failed-rate alert. `suspended`
 * means a graceful shutdown re-queued the session — not an error.
 */
export const sessionOutcomes = new Counter({
    name: 'agent_runner_session_outcomes_total',
    help: 'Sessions that finished a run, by terminal outcome (completed/closed/suspended/failed).',
    labelNames: ['outcome'],
})

/**
 * Crash / pre-run failures broken down by the runner's own `categorize()`
 * output. These are the failures that never reached the driver loop (bad
 * revision, secret-resolver error, sandbox-acquire failure, MCP open) plus any
 * unexpected throw — the ones a deploy is most likely to have just introduced.
 * Graceful in-loop failures show up under `sessionOutcomes{outcome="failed"}`.
 */
export const sessionFailures = new Counter({
    name: 'agent_runner_session_failures_total',
    help: 'Pre-run / crash session failures by error category.',
    labelNames: ['category'],
})

/** Sessions in flight on this worker right now (utilization numerator). */
export const inflightSessions = new Gauge({
    name: 'agent_runner_inflight_sessions',
    help: 'Sessions currently being processed by this worker process.',
})

/** Configured per-worker concurrency ceiling (utilization denominator). */
export const maxConcurrency = new Gauge({
    name: 'agent_runner_max_concurrency',
    help: 'Configured max in-flight sessions per worker (denominator for utilization).',
})

/** Queue `claim()` calls that threw — DB pool unreachable or a malformed row. */
export const claimFailures = new Counter({
    name: 'agent_runner_claim_failures_total',
    help: 'Queue claim() calls that raised (DB unreachable / bad row).',
})

/**
 * Current consecutive claim-failure streak (0 when healthy). The loop backs
 * off exponentially on this; a non-zero plateau means the queue DB is down and
 * the worker is parked, not processing.
 */
export const consecutiveClaimFailures = new Gauge({
    name: 'agent_runner_consecutive_claim_failures',
    help: 'Current consecutive claim() failure streak (0 = healthy).',
})

/**
 * Wall time for one session run. Deliberately NOT labelled by outcome: that
 * would make this histogram's `_count` an exact duplicate of
 * `sessionOutcomes` (same label, incremented together). Counts-by-outcome live
 * on `sessionOutcomes`; this is the overall latency distribution.
 */
export const sessionDuration = new Histogram({
    name: 'agent_runner_session_duration_seconds',
    help: 'Wall-clock duration of one runOne() session run.',
    buckets: [0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800],
})

/** Turns executed per session run — long-tail catches runaway loops. */
export const sessionTurns = new Histogram({
    name: 'agent_runner_session_turns',
    help: 'Turns executed per session run.',
    buckets: [1, 2, 3, 5, 8, 13, 21, 34, 55, 100],
})

/**
 * Sandbox acquire latency + outcome, by provider (modal/docker/in-process).
 * Acquire is a network round-trip to Modal/Docker and a pool gate; a spike
 * here strands every session that needs a custom tool.
 */
export const sandboxAcquire = new Histogram({
    name: 'agent_runner_sandbox_acquire_seconds',
    help: 'Time to acquire a sandbox for a session, by provider + outcome (ok/error).',
    labelNames: ['provider', 'outcome'],
    buckets: [0.1, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120],
})

/** External / integration MCP clients that failed to open at session start, by coarse category. */
export const mcpOpenFailures = new Counter({
    name: 'agent_runner_mcp_open_failures_total',
    help: 'External/integration MCP clients that failed to open at session start, by category.',
    labelNames: ['category'],
})
