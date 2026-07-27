/**
 * Prometheus metrics for the agent-janitor.
 *
 * The janitor is a SINGLETON (min=max=1 pod) running two timers: the sweep
 * (reaps stuck/idle sessions + orphan sandboxes + expired approvals) and the
 * cron tick (fires scheduled triggers). Because it's a singleton, a wedged
 * timer is silent — nothing else reaps — so the `*_runs_total` counters exist
 * precisely so an alert can fire when their rate drops to zero.
 *
 * It also owns the fleet's queue-depth gauge: it samples `countByState()` once
 * per sweep so the `queued` backlog + `running` in-flight totals come from one
 * place instead of every runner pod re-running the same aggregate.
 *
 * The janitor's HTTP surface (Django proxy: /revisions/*, /approvals/*) is
 * intentionally NOT given a request-duration histogram — it's an internal,
 * low-stakes path already latency-traced via the structured-log `instrument()`
 * calls in server.ts, and the fleet's golden-signal HTTP surface is the
 * ingress.
 */

import { Counter, Gauge, Histogram } from '@posthog/agent-shared'

/** Sweep ticks that ran to completion. Rate → 0 means the singleton's sweep timer is wedged. */
export const sweepRuns = new Counter({
    name: 'agent_janitor_sweep_runs_total',
    help: 'Sweep ticks that ran to completion (rate drops to 0 if the singleton wedges).',
})

/** Sweep ticks that threw. */
export const sweepFailures = new Counter({
    name: 'agent_janitor_sweep_failures_total',
    help: 'Sweep ticks that threw.',
})

/** Sweep tick wall time. */
export const sweepDuration = new Histogram({
    name: 'agent_janitor_sweep_duration_seconds',
    help: 'Wall-clock duration of one sweep tick.',
    buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
})

/**
 * Sessions / resources the sweep acted on, by action. `action` ∈ requeued |
 * poisoned | closed | expired_approvals | cleared_idempotency_keys |
 * reaped_sandboxes | sandbox_reap_failures. A rising `requeued` / `poisoned`
 * rate points back at runner instability (workers crashing mid-session);
 * `sandbox_reap_failures` points at the sandbox terminator.
 */
export const sweptTotal = new Counter({
    name: 'agent_janitor_swept_total',
    help: 'Sessions/resources acted on by the sweep, by action.',
    labelNames: ['action'],
})

/** Cron ticks that ran to completion. Rate → 0 means scheduled triggers have stopped firing. */
export const cronRuns = new Counter({
    name: 'agent_janitor_cron_runs_total',
    help: 'Cron ticks that ran to completion (rate drops to 0 if the singleton wedges).',
})

/** Cron ticks that threw. */
export const cronFailures = new Counter({
    name: 'agent_janitor_cron_failures_total',
    help: 'Cron ticks that threw.',
})

/** Cron firings enqueued (scheduled sessions created). */
export const cronFired = new Counter({
    name: 'agent_janitor_cron_fired_total',
    help: 'Cron firings enqueued as sessions.',
})

/** Per-revision cron evaluation errors within a tick (bad schedule, enqueue failure). */
export const cronErrors = new Counter({
    name: 'agent_janitor_cron_errors_total',
    help: 'Per-revision cron evaluation errors within a tick.',
})

/**
 * Fleet session-queue depth by state, sampled once per sweep by this
 * singleton. `state="queued"` is the backlog the runner fleet has to burn
 * down; `state="running"` is in-flight. Known states are zero-filled each
 * sample so a state dropping to 0 is visible rather than frozen at its last
 * value.
 */
export const queueDepth = new Gauge({
    name: 'agent_session_queue_depth',
    help: 'Sessions by state across the fleet, sampled by the janitor singleton.',
    labelNames: ['state'],
})

/** Every session state — used to zero-fill `queueDepth` each sample. */
export const KNOWN_SESSION_STATES = ['queued', 'running', 'completed', 'closed', 'cancelled', 'failed'] as const
