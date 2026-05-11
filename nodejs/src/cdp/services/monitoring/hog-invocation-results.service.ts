import { Counter, Gauge } from 'prom-client'

import { HOG_INVOCATION_RESULTS_OUTPUT, HogInvocationResultsOutput } from '~/ingestion/common/outputs'
import { IngestionOutputs } from '~/ingestion/outputs/ingestion-outputs'

import { safeClickhouseString } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import type { CdpOutput } from '../../cdp-services'
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
 * sharded_hog_invocation_results table. Two such rows are produced per
 * invocation: one when execution starts (`status='running'`) and one when it
 * finishes (`status='succeeded' | 'failed'`). On a replay, the cycle repeats
 * with the same `invocation_id`, `is_retry=1`, and `attempts` bumped — the
 * ReplacingMergeTree on `(team_id, function_kind, function_id, invocation_id)`
 * keyed by `version` collapses prior versions at merge time.
 */
export interface HogInvocationResultRow {
    team_id: number
    function_kind: 'hog_function' | 'hog_flow'
    function_id: string
    invocation_id: string
    parent_run_id: string
    status: 'running' | 'succeeded' | 'failed'
    attempts: number
    is_retry: 0 | 1
    scheduled_at: string // ISO microsecond DateTime64
    started_at: string | null
    finished_at: string | null
    duration_ms: number | null
    error_kind: string
    error_message: string
    event_uuid: string
    distinct_id: string
    person_id: string
    invocation_globals: string // pre-serialized JSON
    version: string // microsecond-precision UInt64; serialized as string to dodge JS's 53-bit precision
    is_deleted: 0 | 1
}

const isHogFunctionInvocation = (invocation: CyclotronJobInvocation): invocation is CyclotronJobInvocationHogFunction =>
    'hogFunction' in invocation

const isHogFlowInvocation = (invocation: CyclotronJobInvocation): invocation is CyclotronJobInvocationHogFlow =>
    'hogFlow' in invocation

const microsecondsSinceEpoch = (): string => {
    // BigInt avoids the 53-bit cap so the number lines up with ClickHouse UInt64.
    const ms = BigInt(Date.now())
    return (ms * 1000n).toString()
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
    if (lower.includes('timeout') || lower.includes('timed out')) {
        kind = 'timeout'
    } else if (lower.match(/\b5\d{2}\b/) || lower.includes('server error')) {
        kind = 'http_5xx'
    } else if (lower.match(/\b4\d{2}\b/)) {
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
// the blast radius of any leak. On replay we re-resolve inputs from the
// current hog function config + integration store, so this is also a no-op
// for replay correctness — we'll always pick up the latest secrets, not a
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

// The full payload that the replay path needs to rehydrate the invocation.
// For hog functions this is the globals tree (event, person, groups, etc.) —
// with `inputs` stripped, see `stripInputs`. For hog flows it's the workflow
// context (event, personId, variables, actionStepCount). Worker-side ZSTD
// compression on the ClickHouse column keeps the storage cost down; we
// serialize plain JSON here.
const serializeInvocationGlobals = (invocation: CyclotronJobInvocation): string => {
    if (isHogFunctionInvocation(invocation)) {
        return JSON.stringify(stripInputs(invocation.state.globals))
    }
    if (isHogFlowInvocation(invocation)) {
        // Hog flow state can carry a per-action `currentAction.hogFunctionState.globals.inputs`
        // — `stripInputs` walks the tree and removes those too.
        return JSON.stringify(stripInputs(invocation.state ?? {}))
    }
    return '{}'
}

const sumDurationMs = (invocation: CyclotronJobInvocation): number | null => {
    if (!isHogFunctionInvocation(invocation)) {
        return null
    }
    const timings = invocation.state?.timings
    if (!timings || timings.length === 0) {
        return null
    }
    return timings.reduce((sum, t) => sum + t.duration_ms, 0)
}

/**
 * Per-invocation lifecycle row producer. Lives next to
 * `HogFunctionMonitoringService` (which handles aggregated metrics + log
 * lines) — this one writes a single row per lifecycle event so the new
 * runs/invocations UI and the replay path can read it back via HogQL.
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
     */
    queueLifecycleRow(
        invocation: CyclotronJobInvocation,
        status: 'running' | 'succeeded' | 'failed',
        opts: {
            error?: unknown
            startedAt?: Date
            finishedAt?: Date
            isRetry?: boolean
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
        const attempts = isHogFunctionInvocation(invocation) ? (invocation.state?.attempts ?? 1) : 1

        const row: HogInvocationResultRow = {
            team_id: invocation.teamId,
            function_kind: this.functionKindFor(invocation),
            function_id: this.functionIdFor(invocation),
            invocation_id: invocation.id,
            parent_run_id: invocation.parentRunId ?? '',
            status,
            attempts,
            is_retry: opts.isRetry ? 1 : 0,
            scheduled_at: isoMicroseconds(invocation.queueScheduledAt?.toJSDate() ?? now),
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

    async flush(): Promise<void> {
        if (this.queuedRows.length === 0) {
            return
        }

        const rows = this.queuedRows
        this.queuedRows = []
        hogInvocationResultsPendingMessages.set(0)

        await Promise.all(
            rows.map((row) => {
                const value = Buffer.from(safeClickhouseString(JSON.stringify(row)))
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
