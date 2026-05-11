import { ClickHouseClient } from '@clickhouse/client'
import { Counter } from 'prom-client'

import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { createHogFlowInvocation } from '../services/hogflows/hogflow-executor.service'
import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogInvocationResultsService } from '../services/monitoring/hog-invocation-results.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobalsWithInputs,
} from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import {
    HOG_INVOCATION_REPLAY_MAX_COUNT,
    REPLAY_PAGE_SIZE,
    ReplayFunctionKind,
    ReplayJobProgress,
    ReplayJobState,
} from './replay-job.types'

const counterReplayPageProcessed = new Counter({
    name: 'cdp_hog_invocation_replay_pages_processed_total',
    help: 'Replay paginator pages processed, by function kind and outcome.',
    labelNames: ['function_kind', 'outcome'],
})

const counterReplayInvocationsQueued = new Counter({
    name: 'cdp_hog_invocation_replay_queued_total',
    help: 'Replayed invocations queued onto cyclotron, by function kind.',
    labelNames: ['function_kind'],
})

const counterReplayInvocationsSkipped = new Counter({
    name: 'cdp_hog_invocation_replay_skipped_total',
    help: 'Invocations matched by replay filters but skipped (over max_attempts, missing function, malformed payload).',
    labelNames: ['function_kind', 'reason'],
})

interface InvocationRow {
    invocation_id: string
    parent_run_id: string
    attempts: number
    scheduled_at: string
    invocation_globals: string
}

export interface PageOutcome {
    /** New job state after this page. The worker writes it back via reschedule(state) — or ack()s if done. */
    state: ReplayJobState
}

/**
 * Processes a single page of work for a replay wrapper job. Pure-ish — the
 * caller (the worker) handles the cyclotron-v2 ack/reschedule flow with the
 * returned state. Splitting the page-of-work logic out of the worker keeps
 * the cyclotron plumbing testable in isolation from the ClickHouse paging.
 */
export class ReplayPaginatorService {
    constructor(
        private clickhouse: ClickHouseClient,
        private hogFunctionManager: HogFunctionManagerService,
        private hogFlowManager: HogFlowManagerService,
        private invocationResultsRowsService: HogInvocationResultsService,
        private cyclotronJobQueue: CyclotronJobQueue
    ) {}

    /**
     * Run one page of work for the given replay job state. Returns the new
     * state. `state.progress.done = true` means the worker should `ack()` the
     * wrapper job; otherwise it should `reschedule({ state })` to continue.
     */
    async processPage(teamId: number, state: ReplayJobState): Promise<PageOutcome> {
        const { function_kind, function_id, request, progress } = state

        try {
            const rows = request.invocation_ids
                ? await this.fetchByIdsPage(teamId, state)
                : await this.fetchByFilterPage(teamId, state)

            if (rows.length === 0) {
                counterReplayPageProcessed.labels(function_kind, 'empty').inc()
                return { state: { ...state, progress: { ...progress, done: true, last_error: undefined } } }
            }

            // Stop early if the user's max_count or our hard server cap is reached.
            const remainingBudget = this.remainingBudget(state)
            const toProcess = rows.slice(0, remainingBudget)

            const { queued, skipped, queuedInvocations } = await this.rehydrateBatch(teamId, state, toProcess)

            if (queuedInvocations.length > 0) {
                await this.cyclotronJobQueue.queueInvocations(queuedInvocations)
                await this.invocationResultsRowsService.flush()
                counterReplayInvocationsQueued.labels(function_kind).inc(queuedInvocations.length)
            }

            const nextProgress: ReplayJobProgress = {
                queued: progress.queued + queued,
                skipped: progress.skipped + skipped,
                cursor: this.advanceCursor(state, toProcess),
                remaining_ids: this.advanceRemainingIds(state, toProcess.length),
                done: this.isDone(state, rows.length, toProcess.length),
                last_error: undefined,
            }

            counterReplayPageProcessed.labels(function_kind, 'ok').inc()

            return { state: { ...state, progress: nextProgress } }
        } catch (err) {
            const errMessage = err instanceof Error ? err.message : String(err)
            logger.error('Replay paginator page failed', {
                replay_function_kind: function_kind,
                replay_function_id: function_id,
                error: errMessage,
            })
            counterReplayPageProcessed.labels(function_kind, 'error').inc()
            // Surface the error in job state but don't mark done — the worker
            // will reschedule, the janitor's transition_count guards against
            // infinite loops on poisoned jobs.
            return { state: { ...state, progress: { ...progress, last_error: errMessage } } }
        }
    }

    private remainingBudget(state: ReplayJobState): number {
        const cap = Math.min(
            state.request.filter?.max_count ?? HOG_INVOCATION_REPLAY_MAX_COUNT,
            HOG_INVOCATION_REPLAY_MAX_COUNT
        )
        return Math.max(0, cap - state.progress.queued - state.progress.skipped)
    }

    private isDone(state: ReplayJobState, fetchedCount: number, processedCount: number): boolean {
        // Done if the page didn't fill the buffer OR we've spent the budget OR
        // we ran out of remaining_ids for the by-ids path.
        const budgetSpent = this.remainingBudget(state) <= processedCount
        const pageWasPartial = fetchedCount < REPLAY_PAGE_SIZE
        if (state.request.invocation_ids) {
            const remaining = state.progress.remaining_ids ?? []
            return budgetSpent || remaining.length <= processedCount
        }
        return budgetSpent || pageWasPartial
    }

    private advanceCursor(state: ReplayJobState, processed: InvocationRow[]): ReplayJobState['progress']['cursor'] {
        if (state.request.invocation_ids) {
            // by-IDs mode doesn't use a keyset cursor.
            return state.progress.cursor ?? null
        }
        if (processed.length === 0) {
            return null
        }
        const last = processed[processed.length - 1]
        return { scheduled_at: last.scheduled_at, invocation_id: last.invocation_id }
    }

    private advanceRemainingIds(state: ReplayJobState, consumedCount: number): string[] | undefined {
        if (!state.request.invocation_ids) {
            return undefined
        }
        const remaining = state.progress.remaining_ids ?? []
        return remaining.slice(consumedCount)
    }

    private async fetchByIdsPage(teamId: number, state: ReplayJobState): Promise<InvocationRow[]> {
        const remaining = state.progress.remaining_ids ?? []
        if (remaining.length === 0) {
            return []
        }
        const slice = remaining.slice(0, REPLAY_PAGE_SIZE)

        const result = await this.clickhouse.query({
            query: `/* team_id:${teamId} query_type:hog_invocation_replay_by_ids_page */
                SELECT
                    invocation_id,
                    argMax(parent_run_id, version)      AS parent_run_id,
                    argMax(attempts, version)           AS attempts,
                    argMax(invocation_globals, version) AS invocation_globals,
                    max(scheduled_at)                   AS scheduled_at
                FROM hog_invocation_results
                WHERE team_id = {team_id:Int64}
                  AND function_kind = {function_kind:String}
                  AND function_id = {function_id:String}
                  AND invocation_id IN {invocation_ids:Array(String)}
                GROUP BY invocation_id
                HAVING argMax(is_deleted, version) = 0`,
            query_params: {
                team_id: teamId,
                function_kind: state.function_kind,
                function_id: state.function_id,
                invocation_ids: slice,
            },
            format: 'JSONEachRow',
        })

        return (await result.json()) as InvocationRow[]
    }

    private async fetchByFilterPage(teamId: number, state: ReplayJobState): Promise<InvocationRow[]> {
        const filter = state.request.filter!
        const requestedStatus = filter.status?.length ? filter.status : ['failed']

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

        const result = await this.clickhouse.query({
            query: `/* team_id:${teamId} query_type:hog_invocation_replay_by_filter_page */
                SELECT
                    invocation_id,
                    argMax(parent_run_id, version)      AS parent_run_id,
                    argMax(attempts, version)           AS attempts,
                    argMax(invocation_globals, version) AS invocation_globals,
                    max(scheduled_at)                   AS scheduled_at
                FROM hog_invocation_results
                WHERE team_id = {team_id:Int64}
                  AND function_kind = {function_kind:String}
                  AND function_id = {function_id:String}
                  AND scheduled_at >= {window_start:DateTime64}
                  AND scheduled_at <  {window_end:DateTime64}
                ${cursorClause}
                GROUP BY invocation_id
                HAVING argMax(is_deleted, version) = 0
                   AND argMax(status, version) IN {status:Array(String)}
                   ${errorKindClause}
                   ${maxAttemptsClause}
                ORDER BY scheduled_at DESC, invocation_id DESC
                LIMIT {limit:UInt32}`,
            query_params: {
                team_id: teamId,
                function_kind: state.function_kind,
                function_id: state.function_id,
                window_start: filter.window_start,
                window_end: filter.window_end,
                status: requestedStatus,
                error_kind: filter.error_kind ?? [],
                max_attempts: filter.max_attempts ?? 255,
                cursor_scheduled_at: cursor?.scheduled_at ?? '',
                cursor_invocation_id: cursor?.invocation_id ?? '',
                limit: REPLAY_PAGE_SIZE,
            },
            format: 'JSONEachRow',
        })

        return (await result.json()) as InvocationRow[]
    }

    private async rehydrateBatch(
        teamId: number,
        state: ReplayJobState,
        rows: InvocationRow[]
    ): Promise<{ queued: number; skipped: number; queuedInvocations: CyclotronJobInvocation[] }> {
        const maxAttempts = state.request.filter?.max_attempts
        const queuedInvocations: CyclotronJobInvocation[] = []
        let skipped = 0

        for (const row of rows) {
            if (maxAttempts !== undefined && row.attempts >= maxAttempts) {
                counterReplayInvocationsSkipped.labels(state.function_kind, 'over_max_attempts').inc()
                skipped++
                continue
            }
            try {
                const invocation = await this.rehydrateInvocation(teamId, state.function_kind, state.function_id, row)
                if (!invocation) {
                    counterReplayInvocationsSkipped.labels(state.function_kind, 'rehydrate_failed').inc()
                    skipped++
                    continue
                }
                // Replay-start lifecycle row. is_retry=1 so the UI marks the row;
                // attempts already incremented by rehydrateInvocation. The matching
                // terminal row is written by the worker when the invocation finishes.
                this.invocationResultsRowsService.queueLifecycleRow(invocation, 'running', { isRetry: true })
                queuedInvocations.push(invocation)
            } catch (e) {
                logger.error('Replay failed to rehydrate invocation', {
                    error: e instanceof Error ? e.message : String(e),
                    invocation_id: row.invocation_id,
                })
                counterReplayInvocationsSkipped.labels(state.function_kind, 'exception').inc()
                skipped++
            }
        }

        return { queued: queuedInvocations.length, skipped, queuedInvocations }
    }

    private async rehydrateInvocation(
        teamId: number,
        functionKind: ReplayFunctionKind,
        functionId: string,
        row: InvocationRow
    ): Promise<CyclotronJobInvocation | null> {
        let parsedGlobals: unknown
        try {
            parsedGlobals = parseJSON(row.invocation_globals)
        } catch {
            return null
        }

        if (functionKind === 'hog_function') {
            const hogFunction = await this.hogFunctionManager.getHogFunction(functionId)
            if (!hogFunction || hogFunction.team_id !== teamId) {
                return null
            }
            const globals = parsedGlobals as HogFunctionInvocationGlobalsWithInputs
            const invocation: CyclotronJobInvocationHogFunction = {
                // Preserve invocation_id so lifecycle rows collapse under the
                // ReplacingMergeTree on the same key.
                id: row.invocation_id,
                state: {
                    globals,
                    timings: [],
                    attempts: row.attempts + 1,
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
            }
            return invocation
        }

        return null
    }
}
