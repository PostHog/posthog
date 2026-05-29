import { ClickHouseClient } from '@clickhouse/client'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { logger } from '../../utils/logger'
import { CyclotronJobConflictError } from '../services/cyclotron-v2'
import { createHogFlowInvocation } from '../services/hogflows/hogflow-executor.service'
import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import {
    HogInvocationResultsService,
    decodeInvocationGlobals,
} from '../services/monitoring/hog-invocation-results.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobalsWithInputs,
} from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { RERUN_PAGE_SIZE, RerunFunctionKind, RerunJobProgress, RerunJobState } from './rerun-job.types'

const counterRerunPageProcessed = new Counter({
    name: 'cdp_hog_invocation_rerun_pages_processed_total',
    help: 'Rerun paginator pages processed, by function kind and outcome.',
    labelNames: ['function_kind', 'outcome'],
})

const counterRerunInvocationsQueued = new Counter({
    name: 'cdp_hog_invocation_rerun_queued_total',
    help: 'Reruned invocations queued onto cyclotron, by function kind.',
    labelNames: ['function_kind'],
})

const counterRerunInvocationsSkipped = new Counter({
    name: 'cdp_hog_invocation_rerun_skipped_total',
    help: 'Invocations matched by rerun filters but skipped (over max_attempts, missing function, malformed payload).',
    labelNames: ['function_kind', 'reason'],
})

// ClickHouse's `DateTime64` parser only accepts 'YYYY-MM-DD HH:MM:SS[.fff]'.
// The Django serializer (and our internal `scheduled_at` column representation)
// uses ISO 8601 with `T` and `Z`. Convert before binding to query params.
const toClickhouseDateTime = (value: string): string => {
    if (!value) {
        return value
    }
    // Already in CH form? Leave it alone.
    if (!value.includes('T')) {
        return value
    }
    return value
        .replace('T', ' ')
        .replace(/Z$/, '')
        .replace(/([+-]\d{2}):?(\d{2})$/, '')
}

interface InvocationRow {
    invocation_id: string
    parent_run_id: string
    attempts: number
    last_scheduled_at: string
    first_scheduled_at: string
    invocation_globals: string
}

export interface PageOutcome {
    /** New job state after this page. The worker writes it back via reschedule(state) — or ack()s if done. */
    state: RerunJobState
}

/**
 * Re-enqueue targets keyed by rerun function kind. Mirrors the split in
 * cdp-events-consumer — hog functions go to kafka, hog flows to postgres-v2.
 * Keying by kind (rather than two positional queue args of similar shape)
 * stops the two backends from being swapped by mistake.
 */
export interface RerunJobQueues {
    hog_function: JobQueue
    hog_flow: CyclotronJobQueuePostgresV2
}

/**
 * Context the worker passes alongside the parsed state on each page. Lets the
 * paginator stamp wrapper lifecycle rows with the right `invocation_id`
 * (= cyclotron job id) and a stable `scheduled_at` for the wrapper across pages.
 */
export interface RerunJobContext {
    jobId: string
    /** When the wrapper job was first created in cyclotron — anchor for the wrapper's `scheduled_at`. */
    createdAt: DateTime
}

/**
 * Processes a single page of work for a rerun wrapper job. Pure-ish — the
 * caller (the worker) handles the cyclotron-v2 ack/reschedule flow with the
 * returned state. Splitting the page-of-work logic out of the worker keeps
 * the cyclotron plumbing testable in isolation from the ClickHouse paging.
 */
export class RerunPaginatorService {
    constructor(
        private clickhouse: ClickHouseClient,
        private hogFunctionManager: HogFunctionManagerService,
        private hogFlowManager: HogFlowManagerService,
        private invocationResultsRowsService: HogInvocationResultsService,
        // Re-enqueue targets keyed by function kind — see RerunJobQueues.
        private jobQueues: RerunJobQueues,
        private monitoringService: HogFunctionMonitoringService,
        // Mirror of the Django serializer cap (HOG_INVOCATION_RERUN_MAX_COUNT env var).
        private maxCount: number
    ) {}

    /**
     * Run one page of work for the given rerun job state. Returns the new
     * state. `state.progress.done = true` means the worker should `ack()` the
     * wrapper job; otherwise it should `reschedule({ state })` to continue.
     */
    async processPage(teamId: number, state: RerunJobState, context: RerunJobContext): Promise<PageOutcome> {
        const { function_kind, function_id, progress } = state

        try {
            const rows = await this.fetchPage(teamId, state)

            // Stop early if the user's max_count or our hard server cap is reached.
            const remainingBudget = this.remainingBudget(state)
            const toProcess = rows.slice(0, remainingBudget)

            const { queued, skipped, queuedInvocations } = await this.rehydrateBatch(teamId, state, toProcess)

            let conflictSkipped = 0
            if (queuedInvocations.length > 0) {
                // Rerun re-uses the original invocation_id. A rerun job is
                // scoped to a single function kind, so the whole page routes to
                // one backend — hog → kafka, hog_flow → postgres-v2, the same
                // split cdp-events-consumer uses.
                let invocationsToEnqueue = queuedInvocations
                if (function_kind === 'hog_flow') {
                    // postgres-v2. `overwriteExisting` upserts ONLY when the
                    // existing cyclotron row is in a terminal state. If a row
                    // is still active, the v2 manager raises
                    // CyclotronJobConflictError listing the conflicting ids —
                    // skip those, still queue the rest.
                    try {
                        await this.jobQueues.hog_flow.queueInvocations(invocationsToEnqueue, {
                            overwriteExisting: true,
                        })
                    } catch (e) {
                        if (!(e instanceof CyclotronJobConflictError)) {
                            throw e
                        }
                        const raw = e.conflictingIds
                        const conflictingIds = new Set(Array.isArray(raw) ? raw : [raw])
                        logger.warn('Rerun skipping invocations that are still in-flight', {
                            rerun_function_kind: function_kind,
                            rerun_function_id: function_id,
                            conflicting_invocation_ids: Array.from(conflictingIds),
                        })
                        conflictSkipped = conflictingIds.size
                        for (let i = 0; i < conflictSkipped; i++) {
                            counterRerunInvocationsSkipped.labels(function_kind, 'still_in_flight').inc()
                        }
                        // The conflicting invocations also queued a 'running'
                        // lifecycle row above — drop them so we don't show a
                        // stale running row for an invocation that didn't
                        // actually re-enqueue.
                        invocationsToEnqueue = queuedInvocations.filter((i) => !conflictingIds.has(i.id))
                        this.invocationResultsRowsService.dropQueuedRowsFor(Array.from(conflictingIds))
                    }
                } else {
                    // kafka. No PK, so a re-enqueue with the original
                    // invocation_id can't conflict — no overwrite path needed.
                    await this.jobQueues.hog_function.queueInvocations(invocationsToEnqueue)
                }
                await this.invocationResultsRowsService.flush()
                counterRerunInvocationsQueued.labels(function_kind).inc(invocationsToEnqueue.length)

                // One debug log per re-enqueued invocation, keyed on its own
                // `instance_id` so the line shows up on that invocation's
                // expanded log panel — not on the wrapper's. Makes it obvious
                // why the run shows up twice when scanning a function's logs.
                const now = DateTime.now()
                this.monitoringService.queueLogs(
                    invocationsToEnqueue.map((inv) => ({
                        team_id: teamId,
                        log_source: function_kind,
                        log_source_id: function_id,
                        instance_id: inv.id,
                        timestamp: now,
                        level: 'debug',
                        message: `Re-queued by re-run job ${context.jobId}.`,
                    })),
                    function_kind
                )
            }

            const nextProgress: RerunJobProgress = {
                queued: progress.queued + queued - conflictSkipped,
                skipped: progress.skipped + skipped + conflictSkipped,
                cursor: this.advanceCursor(state, toProcess),
                done: this.isDone(state, rows.length, toProcess.length),
                last_error: undefined,
                pages_processed: (progress.pages_processed ?? 0) + 1,
            }

            counterRerunPageProcessed.labels(function_kind, rows.length === 0 ? 'empty' : 'ok').inc()

            // Update the wrapper lifecycle row + emit a progress log so the
            // Invocations tab reflects the running total without the user
            // hitting Refresh between pages.
            await this.writeWrapperUpdate(teamId, state, context, nextProgress, undefined)

            return { state: { ...state, progress: nextProgress } }
        } catch (err) {
            const errMessage = err instanceof Error ? err.message : String(err)
            logger.error('Rerun paginator page failed', {
                rerun_function_kind: function_kind,
                rerun_function_id: function_id,
                error: errMessage,
            })
            counterRerunPageProcessed.labels(function_kind, 'error').inc()
            // Surface the error in job state but don't mark done — the worker
            // will reschedule, the janitor's transition_count guards against
            // infinite loops on poisoned jobs.
            const errorProgress = { ...progress, last_error: errMessage }
            await this.writeWrapperUpdate(teamId, state, context, errorProgress, err)
            return { state: { ...state, progress: errorProgress } }
        }
    }

    /**
     * Write a wrapper lifecycle row + log line reflecting the result of one
     * page. Status is `'running'` for in-flight pages, `'succeeded'` /
     * `'failed'` for the final page. Errors flow into the lifecycle row's
     * `error_kind` / `error_message` for failed terminal writes only — a
     * recoverable per-page error gets logged but the row stays `running` so
     * the worker can reschedule and try again.
     *
     * Public so the worker can write a terminal `failed` row from its catch
     * handler when the whole wrapper is being given up on.
     */
    async writeWrapperUpdate(
        teamId: number,
        state: RerunJobState,
        context: RerunJobContext,
        nextProgress: RerunJobProgress,
        pageError: unknown | undefined
    ): Promise<void> {
        const status: 'running' | 'succeeded' | 'failed' = nextProgress.done ? 'succeeded' : 'running'
        const now = new Date()
        this.invocationResultsRowsService.queueRerunWrapperRow({
            teamId,
            parentFunctionKind: state.function_kind,
            functionId: state.function_id,
            rerunJobId: context.jobId,
            status,
            pagesProcessed: nextProgress.pages_processed ?? 0,
            filter: state.request.filter,
            scheduledAt: context.createdAt.toJSDate(),
            startedAt: context.createdAt.toJSDate(),
            finishedAt: status !== 'running' ? now : undefined,
            error: pageError,
        })

        const pageErrorMessage = pageError ? (pageError instanceof Error ? pageError.message : String(pageError)) : null
        const message = nextProgress.done
            ? `Re-run finished. queued=${nextProgress.queued} skipped=${nextProgress.skipped}`
            : pageErrorMessage
              ? `Re-run page failed: ${pageErrorMessage}. Worker will retry.`
              : `Re-run page done. queued=${nextProgress.queued} skipped=${nextProgress.skipped} cursor=${
                    nextProgress.cursor
                        ? `${nextProgress.cursor.scheduled_at}/${nextProgress.cursor.invocation_id}`
                        : 'end'
                }`

        this.monitoringService.queueLogs(
            [
                {
                    team_id: teamId,
                    log_source: state.function_kind,
                    log_source_id: state.function_id,
                    instance_id: context.jobId,
                    timestamp: DateTime.fromJSDate(now),
                    level: pageErrorMessage ? 'warn' : nextProgress.done ? 'info' : 'info',
                    message,
                },
            ],
            state.function_kind
        )

        await Promise.all([this.invocationResultsRowsService.flush(), this.monitoringService.flush()])
    }

    /**
     * Write the terminal `failed` wrapper lifecycle row from the worker's
     * unrecoverable catch path. Logs the cause and flushes so the failure is
     * visible immediately on the Invocations tab.
     */
    async writeWrapperFailure(
        teamId: number,
        state: RerunJobState,
        context: RerunJobContext,
        error: unknown
    ): Promise<void> {
        const errMessage = error instanceof Error ? error.message : String(error)
        const now = new Date()
        this.invocationResultsRowsService.queueRerunWrapperRow({
            teamId,
            parentFunctionKind: state.function_kind,
            functionId: state.function_id,
            rerunJobId: context.jobId,
            status: 'failed',
            pagesProcessed: state.progress.pages_processed ?? 0,
            filter: state.request.filter,
            scheduledAt: context.createdAt.toJSDate(),
            startedAt: context.createdAt.toJSDate(),
            finishedAt: now,
            error,
        })

        this.monitoringService.queueLogs(
            [
                {
                    team_id: teamId,
                    log_source: state.function_kind,
                    log_source_id: state.function_id,
                    instance_id: context.jobId,
                    timestamp: DateTime.fromJSDate(now),
                    level: 'error',
                    message: `Re-run aborted: ${errMessage}`,
                },
            ],
            state.function_kind
        )

        await Promise.all([this.invocationResultsRowsService.flush(), this.monitoringService.flush()])
    }

    private remainingBudget(state: RerunJobState): number {
        const cap = Math.min(state.request.filter.max_count ?? this.maxCount, this.maxCount)
        return Math.max(0, cap - state.progress.queued - state.progress.skipped)
    }

    private isDone(state: RerunJobState, fetchedCount: number, processedCount: number): boolean {
        const budgetSpent = this.remainingBudget(state) <= processedCount
        const pageWasPartial = fetchedCount < RERUN_PAGE_SIZE
        return budgetSpent || pageWasPartial
    }

    private advanceCursor(state: RerunJobState, processed: InvocationRow[]): RerunJobState['progress']['cursor'] {
        if (processed.length === 0) {
            return null
        }
        const last = processed[processed.length - 1]
        return { scheduled_at: last.last_scheduled_at, invocation_id: last.invocation_id }
    }

    private async fetchPage(teamId: number, state: RerunJobState): Promise<InvocationRow[]> {
        const filter = state.request.filter
        const requestedStatus = filter.status?.length ? filter.status : ['failed']
        // The Django serializer accepts ISO 8601 ('2026-05-01T00:00:00Z'), but
        // ClickHouse `DateTime64` only parses 'YYYY-MM-DD HH:MM:SS[.fff]'. Convert
        // before passing as a query parameter.
        const windowStart = toClickhouseDateTime(filter.window_start)
        const windowEnd = toClickhouseDateTime(filter.window_end)
        const cursorScheduledAt = state.progress.cursor?.scheduled_at
            ? toClickhouseDateTime(state.progress.cursor.scheduled_at)
            : ''

        // Keyset pagination on (scheduled_at, invocation_id). When the cursor
        // is undefined we start from the top of the window. ClickHouse needs
        // the tuple compared via a single AND-chained inequality.
        const cursor = state.progress.cursor
        const cursorClause =
            cursor && cursor.scheduled_at
                ? '   AND (scheduled_at, invocation_id) < ({cursor_scheduled_at:DateTime64}, {cursor_invocation_id:String})'
                : ''
        const errorKindClause = filter.error_kind?.length
            ? 'AND argMax(error_kind, version) IN {error_kind:Array(String)}'
            : ''
        const maxAttemptsClause =
            filter.max_attempts !== undefined ? 'AND argMax(attempts, version) < {max_attempts:UInt8}' : ''
        // `invocation_ids` is an OPTIONAL additional restriction layered on top
        // of the time window. The window is still required — it pins the query
        // to a small set of date partitions instead of scanning everything.
        const invocationIdsClause = filter.invocation_ids?.length
            ? 'AND invocation_id IN {invocation_ids:Array(String)}'
            : ''

        const result = await this.clickhouse.query({
            query: `/* team_id:${teamId} query_type:hog_invocation_rerun_page */
                SELECT
                    invocation_id,
                    argMax(parent_run_id, version)         AS parent_run_id,
                    argMax(attempts, version)              AS attempts,
                    argMax(invocation_globals, version)    AS invocation_globals,
                    argMax(first_scheduled_at, version)    AS first_scheduled_at,
                    max(scheduled_at)                      AS last_scheduled_at
                FROM hog_invocation_results
                WHERE team_id = {team_id:Int64}
                  AND function_kind = {function_kind:String}
                  AND function_id = {function_id:String}
                  AND scheduled_at >= {window_start:DateTime64}
                  AND scheduled_at <  {window_end:DateTime64}
                  ${invocationIdsClause}
                ${cursorClause}
                GROUP BY invocation_id
                HAVING argMax(is_deleted, version) = 0
                   AND argMax(status, version) IN {status:Array(String)}
                   ${errorKindClause}
                   ${maxAttemptsClause}
                ORDER BY last_scheduled_at DESC, invocation_id DESC
                LIMIT {limit:UInt32}`,
            query_params: {
                team_id: teamId,
                function_kind: state.function_kind,
                function_id: state.function_id,
                window_start: windowStart,
                window_end: windowEnd,
                status: requestedStatus,
                error_kind: filter.error_kind ?? [],
                max_attempts: filter.max_attempts ?? 255,
                invocation_ids: filter.invocation_ids ?? [],
                cursor_scheduled_at: cursorScheduledAt,
                cursor_invocation_id: cursor?.invocation_id ?? '',
                limit: RERUN_PAGE_SIZE,
            },
            format: 'JSONEachRow',
        })

        return (await result.json()) as InvocationRow[]
    }

    private async rehydrateBatch(
        teamId: number,
        state: RerunJobState,
        rows: InvocationRow[]
    ): Promise<{ queued: number; skipped: number; queuedInvocations: CyclotronJobInvocation[] }> {
        const maxAttempts = state.request.filter.max_attempts

        // Rehydrate the whole page concurrently — `addGroupsToGlobals` and the
        // hog function manager are LazyLoader-backed and batch their DB lookups
        // across concurrent callers, so a sequential loop would defeat that.
        const rehydrated = await Promise.all(
            rows.map(async (row): Promise<CyclotronJobInvocation | null> => {
                if (maxAttempts !== undefined && row.attempts >= maxAttempts) {
                    counterRerunInvocationsSkipped.labels(state.function_kind, 'over_max_attempts').inc()
                    return null
                }
                try {
                    const invocation = await this.rehydrateInvocation(
                        teamId,
                        state.function_kind,
                        state.function_id,
                        row
                    )
                    if (!invocation) {
                        counterRerunInvocationsSkipped.labels(state.function_kind, 'rehydrate_failed').inc()
                    }
                    return invocation
                } catch (e) {
                    logger.error('Rerun failed to rehydrate invocation', {
                        error: e instanceof Error ? e.message : String(e),
                        invocation_id: row.invocation_id,
                    })
                    counterRerunInvocationsSkipped.labels(state.function_kind, 'exception').inc()
                    return null
                }
            })
        )

        const queuedInvocations: CyclotronJobInvocation[] = []
        for (const invocation of rehydrated) {
            if (!invocation) {
                continue
            }
            // Rerun-start lifecycle row. is_retry/attempts are derived from
            // `state.rerunAttempts` (set by rehydrateInvocation). The matching
            // terminal row is written by the worker when the invocation
            // finishes — same derivation, same is_retry=1.
            this.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
            queuedInvocations.push(invocation)
        }

        return {
            queued: queuedInvocations.length,
            skipped: rows.length - queuedInvocations.length,
            queuedInvocations,
        }
    }

    private async rehydrateInvocation(
        teamId: number,
        functionKind: RerunFunctionKind,
        functionId: string,
        row: InvocationRow
    ): Promise<CyclotronJobInvocation | null> {
        let parsedGlobals: unknown
        try {
            parsedGlobals = await decodeInvocationGlobals(row.invocation_globals)
        } catch {
            return null
        }

        if (functionKind === 'hog_function') {
            const hogFunction = await this.hogFunctionManager.getHogFunction(functionId)
            if (!hogFunction || hogFunction.team_id !== teamId) {
                return null
            }
            // The persisted globals are minimal — `inputs`, `groups` and
            // `person` are all stripped. Re-enqueue as-is: the cyclotron worker
            // rehydrates `groups`/`person` and the executor rebuilds `inputs`
            // from the current hog function config, so the rerun runs against
            // the latest config/secrets rather than a stored snapshot.
            const persistedGlobals = parsedGlobals as HogFunctionInvocationGlobalsWithInputs
            const invocation: CyclotronJobInvocationHogFunction = {
                // Preserve invocation_id so lifecycle rows collapse under the
                // ReplacingMergeTree on the same key.
                id: row.invocation_id,
                state: {
                    globals: persistedGlobals,
                    timings: [],
                    // `attempts` is the fetch-retry counter and is reset to 0
                    // for the rerun run. `rerunAttempts` (read from the
                    // stored row's `attempts` column, which holds the prior
                    // rerun count) drives `is_retry` and `attempts` on the
                    // lifecycle rows.
                    attempts: 0,
                    rerunAttempts: (row.attempts || 0) + 1,
                    // Carry the original first-scheduled time forward — the
                    // producer writes this verbatim on every retry's lifecycle
                    // rows so ReplacingMergeTree doesn't collapse it away.
                    firstScheduledAt: row.first_scheduled_at,
                },
                teamId,
                functionId,
                parentRunId: row.parent_run_id || null,
                hogFunction,
                queue: 'hog',
                queuePriority: 0,
            }
            return invocation
        }

        if (functionKind === 'hog_flow') {
            const hogFlow = await this.hogFlowManager.getHogFlow(functionId)
            if (!hogFlow || hogFlow.team_id !== teamId) {
                return null
            }
            const persistedState = parsedGlobals as Record<string, any>
            const eventForFilter = persistedState.event ?? {}
            const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal({
                event: eventForFilter,
                person: undefined,
                groups: {},
                variables: persistedState.variables ?? {},
            } as any)

            const invocation: CyclotronJobInvocationHogFlow = createHogFlowInvocation(
                {
                    project: { id: teamId, name: '', url: '' },
                    event: eventForFilter,
                    person: undefined,
                    groups: {},
                    variables: persistedState.variables ?? {},
                    source: { name: '', url: '' },
                } as any,
                hogFlow,
                filterGlobals
            )
            invocation.id = row.invocation_id
            invocation.parentRunId = row.parent_run_id || null
            invocation.state = {
                ...invocation.state!,
                event: eventForFilter,
                actionStepCount: persistedState.actionStepCount ?? 0,
                variables: persistedState.variables ?? {},
                // Sticky rerun counter — mirror the hog function path so the
                // lifecycle row producer can derive `attempts` / `is_retry`
                // for flows too, and the `max_attempts` guard actually trips.
                rerunAttempts: (row.attempts || 0) + 1,
                firstScheduledAt: row.first_scheduled_at,
            }
            return invocation
        }

        return null
    }
}
