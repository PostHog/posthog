import { promisify } from 'node:util'
import { gunzip, gzip } from 'node:zlib'
import { Counter, Gauge } from 'prom-client'

import { HOG_INVOCATION_RESULTS_OUTPUT, HogInvocationResultsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { safeClickhouseString } from '~/common/utils/db/utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import type { CdpOutput } from '../../cdp-services'
import { RerunFilter, RerunFunctionKind, rerunWrapperKindFor } from '../../rerun/rerun-job.types'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
} from '../../types'

const counterHogInvocationResultRowsProduced = new Counter({
    name: 'cdp_hog_invocation_result_rows_produced',
    help: 'Lifecycle rows queued for the hog_invocation_results ClickHouse table.',
    labelNames: ['function_kind', 'status'],
})

const counterHogInvocationResultProduceFailed = new Counter({
    name: 'cdp_hog_invocation_result_produce_failed',
    help: 'Rows that failed to produce to Kafka.',
})

const hogInvocationResultsPendingMessages = new Gauge({
    name: 'cdp_hog_invocation_results_pending_messages',
    help: 'Rows queued waiting to be flushed to Kafka.',
})

export type HogInvocationResultsServiceOutput = HogInvocationResultsOutput | CdpOutput

/**
 * Lifecycle row produced to ClickHouse via Kafka. Mirrors the columns on the
 * hog_invocation_results_data table. Two such rows are produced per
 * invocation: one when execution starts (`status='running'`) and one when it
 * finishes (`status='succeeded' | 'failed'`). On a rerun, the cycle repeats
 * with the same `invocation_id`, `is_retry=1`, and `attempts` bumped — the
 * ReplacingMergeTree on `(team_id, function_kind, function_id, invocation_id)`
 * keyed by `version` collapses prior versions at merge time.
 */
export interface HogInvocationResultRow {
    team_id: number
    // `*_rerun` kinds tag the wrapper row that drives a re-run, so the
    // Invocations list can surface in-flight re-runs alongside the function's
    // normal invocations. See `rerun-job.types.ts` for the helper.
    function_kind: 'hog_function' | 'hog_flow' | 'hog_function_rerun' | 'hog_flow_rerun'
    function_id: string
    invocation_id: string
    parent_run_id: string
    status: 'running' | 'succeeded' | 'failed'
    attempts: number
    is_retry: 0 | 1
    scheduled_at: string // ISO microsecond DateTime64
    // Original cyclotron-scheduled time, carried unchanged through retries.
    // ReplacingMergeTree collapses lifecycle rows per invocation_id, so
    // `min(scheduled_at)` post-merge is unreliable — every row stamps this
    // verbatim so `argMax(first_scheduled_at, version)` returns it correctly.
    first_scheduled_at: string
    started_at: string | null
    finished_at: string | null
    duration_ms: number | null
    error_kind: string
    error_message: string
    event_uuid: string
    distinct_id: string
    person_id: string
    invocation_globals: string // globals JSON (inputs/groups/person stripped) — gzip+base64'd on produce
    version: string // microsecond-precision UInt64; serialized as string to dodge JS's 53-bit precision
    is_deleted: 0 | 1
}

const isHogFunctionInvocation = (invocation: CyclotronJobInvocation): invocation is CyclotronJobInvocationHogFunction =>
    'hogFunction' in invocation

const isHogFlowInvocation = (invocation: CyclotronJobInvocation): invocation is CyclotronJobInvocationHogFlow =>
    'hogFlow' in invocation

// Sub-ms-precision epoch timestamp that stays monotonic within a process, so
// consecutive lifecycle rows for the same invocation get strictly increasing
// `version` values. Without monotonicity the 'running' + terminal rows of a
// fast invocation can share (or invert) a `version`, and ReplacingMergeTree
// keeps one arbitrarily — potentially leaving the runs UI showing a
// permanently 'running' status.
//
// Both the millisecond and sub-ms parts come from the SAME monotonic source:
// `performance.timeOrigin` (wall-clock ms at process start) plus
// `performance.now()` (monotonic ms since then). Deriving the ms part from
// `Date.now()` instead would not be monotonic — the wall clock can step
// backward (NTP), and its ms boundary is uncorrelated with `performance.now()`'s
// sub-ms fraction, so the two clocks could disagree and invert the version. The
// only remaining tie window is two rows sampled at the exact same
// `performance.now()`, which is below the precision the clock delivers.
const microsecondsSinceEpoch = (): string => {
    const epochMs = performance.timeOrigin + performance.now()
    // BigInt avoids the 53-bit cap so the number lines up with ClickHouse UInt64.
    const ms = BigInt(Math.floor(epochMs))
    const subMs = BigInt(Math.floor((epochMs % 1) * 1000))
    return (ms * 1000n + subMs).toString()
}

const isoMicroseconds = (date: Date): string => {
    // ClickHouse DateTime64(6) accepts 'YYYY-MM-DD HH:MM:SS.ffffff'.
    return date.toISOString().replace('T', ' ').replace('Z', '000')
}

const truncate = (value: string, max: number): string => {
    if (value.length <= max) {
        return value
    }
    return value.slice(0, max)
}

// Best-effort error classification — keeps `error_kind` low-cardinality so the
// status_idx skipping index stays small. The full message lands in
// `error_message`, the full stack stays in log_entries.
const classifyError = (error: unknown): { kind: string; message: string } => {
    if (!error) {
        return { kind: '', message: '' }
    }
    const message =
        typeof error === 'string'
            ? error
            : error instanceof Error
              ? error.stack || error.message
              : (() => {
                    try {
                        return JSON.stringify(error)
                    } catch {
                        return String(error)
                    }
                })()

    const lower = message.toLowerCase()
    let kind = 'hog_error'
    // Anchor the status-code patterns to HTTP-context tokens so messages like
    // "processed 500 items" or "400 rows returned" don't get misclassified as
    // http_5xx / http_4xx. Matches: 'status 503', 'http 502', 'http/2 504',
    // 'status code 500', etc.
    const http5xxRegex = /\b(?:status(?:\s*code)?|http(?:[/ ]\d)?)\s*[:= ]?\s*5\d{2}\b/
    const http4xxRegex = /\b(?:status(?:\s*code)?|http(?:[/ ]\d)?)\s*[:= ]?\s*4\d{2}\b/
    if (lower.includes('timeout') || lower.includes('timed out')) {
        kind = 'timeout'
    } else if (http5xxRegex.test(lower) || lower.includes('server error')) {
        kind = 'http_5xx'
    } else if (http4xxRegex.test(lower)) {
        kind = 'http_4xx'
    } else if (lower.includes('out of memory') || lower.includes('oom')) {
        kind = 'oom'
    }

    return { kind, message: truncate(message, 4096) }
}

const extractTriggerFields = (
    invocation: CyclotronJobInvocation
): { event_uuid: string; distinct_id: string; person_id: string } => {
    if (isHogFunctionInvocation(invocation)) {
        const globals = invocation.state.globals
        return {
            event_uuid: globals.event?.uuid ?? '',
            distinct_id: globals.event?.distinct_id ?? '',
            person_id: globals.person?.id ?? '',
        }
    }

    if (isHogFlowInvocation(invocation)) {
        const event = invocation.state?.event
        return {
            event_uuid: event?.uuid ?? '',
            distinct_id: event?.distinct_id ?? '',
            person_id: invocation.state?.personId ?? invocation.person?.id ?? '',
        }
    }

    return { event_uuid: '', distinct_id: '', person_id: '' }
}

// Strip every `inputs` blob we can find on a globals/state tree. `inputs`
// holds resolved input values for the function — these can include user-
// supplied secrets (API keys, OAuth tokens, etc.) that the function templated
// in at execute time. Persisting them to ClickHouse for 30 days would expand
// the blast radius of any leak. On rerun we re-resolve inputs from the
// current hog function config + integration store, so this is also a no-op
// for rerun correctness — we'll always pick up the latest secrets, not a
// snapshot from when the original invocation ran.
const stripInputs = <T>(value: T): T => {
    if (value === null || typeof value !== 'object') {
        return value
    }
    if (Array.isArray(value)) {
        // We don't expect inputs to live inside arrays today; this branch is a
        // defensive cheap pass-through so a future schema change doesn't have
        // to come back here.
        return value.map((item) => stripInputs(item)) as unknown as T
    }
    const obj = value as Record<string, unknown>
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(obj)) {
        if (k === 'inputs') {
            continue
        }
        out[k] = stripInputs(v)
    }
    return out as T
}

// The payload the rerun path needs to rehydrate the invocation, kept minimal.
// `inputs`, `groups` and `person` are all dropped: the cyclotron worker
// rehydrates `groups`/`person` (loadHogFunctions) and the executor rebuilds
// `inputs` when an invocation arrives without them — so the rerun reconstructs
// everything from the event against the latest config. `inputs` must be
// dropped anyway for security (resolved secrets — see `stripInputs`).
const serializeInvocationGlobals = (invocation: CyclotronJobInvocation): string => {
    if (isHogFunctionInvocation(invocation)) {
        const { groups: _groups, person: _person, ...globals } = invocation.state.globals
        return JSON.stringify(stripInputs(globals))
    }
    if (isHogFlowInvocation(invocation)) {
        // Hog flow state can carry a per-action `currentAction.hogFunctionState.globals.inputs`
        // — `stripInputs` walks the tree and removes those too.
        return JSON.stringify(stripInputs(invocation.state ?? {}))
    }
    return '{}'
}

const gzipAsync = promisify(gzip)
const gunzipAsync = promisify(gunzip)

// `invocation_globals` is the bulk of every lifecycle row. Warpstream meters
// the uncompressed message bytes, so gzipping this one field before produce
// directly cuts cyclotron throughput. The row envelope stays plain JSON — only
// this field is opaque — so the ClickHouse Kafka engine still parses the
// message as JSONEachRow. `decodeInvocationGlobals` is the inverse.
const compressInvocationGlobals = async (globalsJson: string): Promise<string> => {
    return (await gzipAsync(globalsJson)).toString('base64')
}

/**
 * Inverse of `compressInvocationGlobals`. Used by the rerun paginator to read
 * `invocation_globals` back off ClickHouse. Rows written before field
 * compression landed are still raw JSON — base64 can never start with `{`, so
 * the prefix is an unambiguous discriminator for the legacy fallback.
 */
export const decodeInvocationGlobals = async (stored: string): Promise<unknown> => {
    if (stored.startsWith('{')) {
        return parseJSON(stored)
    }
    return parseJSON((await gunzipAsync(Buffer.from(stored, 'base64'))).toString('utf8'))
}

const sumDurationMs = (invocation: CyclotronJobInvocation): number | null => {
    if (!isHogFunctionInvocation(invocation)) {
        return null
    }
    const timings = invocation.state?.timings
    if (!timings || timings.length === 0) {
        return null
    }
    // Per-step timings are fractional ms (perf.now() deltas). ClickHouse stores
    // duration_ms as UInt32 — Kafka's JSONEachRow parser rejects the row if the
    // field arrives as a float, so round before serialization.
    return Math.round(timings.reduce((sum, t) => sum + t.duration_ms, 0))
}

/**
 * Per-invocation lifecycle row producer. Lives next to
 * `HogFunctionMonitoringService` (which handles aggregated metrics + log
 * lines) — this one writes a single row per lifecycle event so the new
 * runs/invocations UI and the rerun path can read it back via HogQL.
 *
 * Off by default behind `config.HOG_INVOCATION_RESULTS_ENABLED`. Producing
 * rows for filtered-out events is intentionally skipped — the worker only
 * calls into this service for invocations that are actually queued to run.
 */
export class HogInvocationResultsService {
    private queuedRows: HogInvocationResultRow[] = []

    constructor(
        private outputs: IngestionOutputs<HogInvocationResultsServiceOutput>,
        private config: { HOG_INVOCATION_RESULTS_ENABLED: boolean }
    ) {}

    private functionIdFor(invocation: CyclotronJobInvocation): string {
        if (isHogFunctionInvocation(invocation)) {
            return invocation.hogFunction.id
        }
        if (isHogFlowInvocation(invocation)) {
            return invocation.hogFlow.id
        }
        return invocation.functionId
    }

    private functionKindFor(invocation: CyclotronJobInvocation): 'hog_function' | 'hog_flow' {
        return isHogFlowInvocation(invocation) ? 'hog_flow' : 'hog_function'
    }

    /**
     * Queue a lifecycle row. `status='running'` should be called when the
     * worker dequeues an invocation and is about to execute it; `succeeded` /
     * `failed` are derived inside `queueInvocationResults` from the result.
     *
     * `attempts` and `is_retry` are derived from `invocation.state.rerunAttempts`
     * — set by the rerun paginator on rehydration and never touched by the
     * executor's fetch-retry counter (`state.attempts`).
     */
    queueLifecycleRow(
        invocation: CyclotronJobInvocation,
        status: 'running' | 'succeeded' | 'failed',
        opts: {
            error?: unknown
            startedAt?: Date
            finishedAt?: Date
        } = {}
    ): void {
        if (!this.config.HOG_INVOCATION_RESULTS_ENABLED) {
            return
        }

        const now = new Date()
        const trigger = extractTriggerFields(invocation)
        const { kind: errorKind, message: errorMessage } = classifyError(opts.error)
        const startedAt = opts.startedAt ?? (status === 'running' ? now : undefined)
        const finishedAt = opts.finishedAt ?? (status !== 'running' ? now : undefined)
        const durationMs =
            startedAt && finishedAt
                ? Math.max(0, finishedAt.getTime() - startedAt.getTime())
                : sumDurationMs(invocation)
        // Both hog function and hog flow state carry a `rerunAttempts`
        // counter that the rerun paginator increments on rehydration. Read
        // from whichever shape this invocation is so the `max_attempts` guard
        // applies uniformly.
        const rerunAttempts = isHogFunctionInvocation(invocation)
            ? (invocation.state?.rerunAttempts ?? 0)
            : isHogFlowInvocation(invocation)
              ? (invocation.state?.rerunAttempts ?? 0)
              : 0

        // `firstScheduledAt` records the original cyclotron-scheduled time. The
        // rerun paginator sets it on rehydration; here we also stamp it onto the
        // state the first time we emit a 'running' row, so it survives cyclotron
        // fetch retries (which overwrite `queueScheduledAt`). The 'running' row
        // fires once at invocation creation, before the invocation is enqueued,
        // so the value carries forward in the serialized state. Without this the
        // terminal row — written after a retry — would record the retry time and
        // win the ReplacingMergeTree argMax, mislabeling the run's start time.
        let firstScheduledAt = isHogFunctionInvocation(invocation)
            ? invocation.state?.firstScheduledAt
            : isHogFlowInvocation(invocation)
              ? invocation.state?.firstScheduledAt
              : undefined
        const scheduledAtIso = isoMicroseconds(invocation.queueScheduledAt?.toJSDate() ?? now)
        if (status === 'running' && firstScheduledAt === undefined) {
            firstScheduledAt = scheduledAtIso
            if (isHogFunctionInvocation(invocation)) {
                invocation.state.firstScheduledAt = scheduledAtIso
            } else if (isHogFlowInvocation(invocation) && invocation.state) {
                invocation.state.firstScheduledAt = scheduledAtIso
            }
        }

        const row: HogInvocationResultRow = {
            team_id: invocation.teamId,
            function_kind: this.functionKindFor(invocation),
            function_id: this.functionIdFor(invocation),
            invocation_id: invocation.id,
            parent_run_id: invocation.parentRunId ?? '',
            status,
            attempts: rerunAttempts,
            is_retry: rerunAttempts > 0 ? 1 : 0,
            scheduled_at: scheduledAtIso,
            first_scheduled_at: firstScheduledAt ?? scheduledAtIso,
            started_at: startedAt ? isoMicroseconds(startedAt) : null,
            finished_at: finishedAt ? isoMicroseconds(finishedAt) : null,
            duration_ms: durationMs,
            error_kind: errorKind,
            error_message: errorMessage,
            event_uuid: trigger.event_uuid,
            distinct_id: trigger.distinct_id,
            person_id: trigger.person_id,
            invocation_globals: serializeInvocationGlobals(invocation),
            version: microsecondsSinceEpoch(),
            is_deleted: 0,
        }

        counterHogInvocationResultRowsProduced.labels(row.function_kind, row.status).inc()
        this.queuedRows.push(row)
        hogInvocationResultsPendingMessages.set(this.queuedRows.length)
    }

    /**
     * Queue a lifecycle row for a re-run wrapper job.
     *
     * Conceptually a wrapper is a meta-invocation: one row per re-run rather
     * than one per rerun invocation. Stamping it on `hog_invocation_results`
     * (with `function_kind = *_rerun`) means the same Invocations tab is the
     * only debugging surface for both real invocations and the wrappers that
     * spawned them — no separate polling, no separate UI.
     *
     * Fields we deliberately leave empty: `event_uuid` / `distinct_id` /
     * `person_id` — a wrapper isn't triggered by a single event. The filter
     * blob goes in `invocation_globals` (never exposed via HogQL — same
     * security guarantee as for normal invocations).
     */
    queueRerunWrapperRow(args: {
        teamId: number
        parentFunctionKind: RerunFunctionKind
        functionId: string
        rerunJobId: string
        status: 'running' | 'succeeded' | 'failed'
        pagesProcessed: number
        filter: RerunFilter
        scheduledAt: Date
        startedAt?: Date
        finishedAt?: Date
        error?: unknown
    }): void {
        if (!this.config.HOG_INVOCATION_RESULTS_ENABLED) {
            return
        }

        const { kind: errorKind, message: errorMessage } = classifyError(args.error)
        const durationMs =
            args.startedAt && args.finishedAt ? Math.max(0, args.finishedAt.getTime() - args.startedAt.getTime()) : null

        const scheduledAtIso = isoMicroseconds(args.scheduledAt)
        const row: HogInvocationResultRow = {
            team_id: args.teamId,
            function_kind: rerunWrapperKindFor(args.parentFunctionKind),
            function_id: args.functionId,
            invocation_id: args.rerunJobId,
            parent_run_id: '',
            status: args.status,
            attempts: args.pagesProcessed,
            is_retry: 0,
            scheduled_at: scheduledAtIso,
            // Wrapper rows don't have retries — first == scheduled. Keeping
            // the field populated so the column reads consistently across
            // both row kinds.
            first_scheduled_at: scheduledAtIso,
            started_at: args.startedAt ? isoMicroseconds(args.startedAt) : null,
            finished_at: args.finishedAt ? isoMicroseconds(args.finishedAt) : null,
            duration_ms: durationMs,
            error_kind: errorKind,
            error_message: errorMessage,
            event_uuid: '',
            distinct_id: '',
            person_id: '',
            invocation_globals: JSON.stringify(args.filter),
            version: microsecondsSinceEpoch(),
            is_deleted: 0,
        }

        counterHogInvocationResultRowsProduced.labels(row.function_kind, row.status).inc()
        this.queuedRows.push(row)
        hogInvocationResultsPendingMessages.set(this.queuedRows.length)
    }

    queueInvocationResults(results: CyclotronJobInvocationResult[]): void {
        if (!this.config.HOG_INVOCATION_RESULTS_ENABLED) {
            return
        }

        for (const result of results) {
            if (!(result.finished || result.error)) {
                // Mid-flight intermediate update — no terminal row yet. The
                // 'running' row was emitted at execution start; nothing else
                // to write until completion.
                continue
            }

            const status: 'succeeded' | 'failed' = result.error ? 'failed' : 'succeeded'
            this.queueLifecycleRow(result.invocation, status, { error: result.error })
        }
    }

    /**
     * Discard any queued (un-flushed) lifecycle rows for the given invocation
     * ids. Used by the rerun paginator when a re-enqueue is refused (existing
     * job is still in-flight) — we already queued a 'running' row for that
     * invocation_id; drop it so we don't surface a stale running marker.
     */
    dropQueuedRowsFor(invocationIds: string[]): void {
        if (invocationIds.length === 0) {
            return
        }
        const drop = new Set(invocationIds)
        this.queuedRows = this.queuedRows.filter((r) => !drop.has(r.invocation_id))
        hogInvocationResultsPendingMessages.set(this.queuedRows.length)
    }

    async flush(): Promise<void> {
        if (this.queuedRows.length === 0) {
            return
        }

        const rows = this.queuedRows
        this.queuedRows = []
        hogInvocationResultsPendingMessages.set(0)

        await Promise.all(
            rows.map(async (row) => {
                const value = Buffer.from(
                    safeClickhouseString(
                        JSON.stringify({
                            ...row,
                            invocation_globals: await compressInvocationGlobals(row.invocation_globals),
                        })
                    )
                )
                return this.outputs
                    .produce(HOG_INVOCATION_RESULTS_OUTPUT, {
                        // Partition by invocation_id so all rows for a single
                        // invocation land on the same Kafka partition (and
                        // therefore the same ClickHouse shard via
                        // cityHash64(invocation_id) — keeping the
                        // ReplacingMergeTree merge local).
                        key: Buffer.from(row.invocation_id),
                        value,
                    })
                    .catch((error) => {
                        counterHogInvocationResultProduceFailed.inc()
                        // Best-effort — never disrupt invocation processing
                        // for a monitoring write.
                        logger.error('⚠️', `failed to produce hog invocation result: ${error}`, {
                            error: String(error),
                            invocation_id: row.invocation_id,
                        })
                        captureException(error)
                    })
            })
        )
    }
}
