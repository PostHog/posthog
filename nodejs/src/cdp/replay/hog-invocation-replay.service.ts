import { ClickHouseClient } from '@clickhouse/client'
import { Counter } from 'prom-client'

import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
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

// Hard server-side cap. Mirrors HOG_INVOCATION_REPLAY_MAX_COUNT in
// posthog/api/hog_invocation_replay.py — keep both in sync.
export const HOG_INVOCATION_REPLAY_MAX_COUNT = 1000

export type ReplayFunctionKind = 'hog_function' | 'hog_flow'

export interface ReplayFilter {
    window_start: string
    window_end: string
    status?: ('running' | 'succeeded' | 'failed')[]
    error_kind?: string[]
    max_attempts?: number
    max_count?: number
}

export interface ReplayRequest {
    invocation_ids?: string[]
    filter?: ReplayFilter
}

export interface ReplayResult {
    queued_count: number
    skipped_count: number
}

interface InvocationRow {
    invocation_id: string
    parent_run_id: string
    attempts: number
    invocation_globals: string
}

/**
 * Reads matching rows from ClickHouse `hog_invocation_results`, rehydrates
 * each invocation from its stored `invocation_globals`, and re-enqueues onto
 * cyclotron with `is_retry=1`.
 *
 * The query collapses the ReplacingMergeTree the same way the listing query
 * does: GROUP BY invocation_id, project the latest row's value via
 * argMax(field, version). Pagination is keyset on (scheduled_at, invocation_id)
 * so a long-running by-filter request can resume.
 */
export class HogInvocationReplayService {
    constructor(
        private clickhouse: ClickHouseClient,
        private hogFunctionManager: HogFunctionManagerService,
        private hogFlowManager: HogFlowManagerService,
        private invocationResultsRowsService: HogInvocationResultsService,
        private cyclotronJobQueue: CyclotronJobQueue
    ) {}

    async replay(
        teamId: number,
        functionKind: ReplayFunctionKind,
        functionId: string,
        request: ReplayRequest
    ): Promise<ReplayResult> {
        const rows = request.invocation_ids?.length
            ? await this.fetchByIds(teamId, functionKind, functionId, request.invocation_ids)
            : await this.fetchByFilter(teamId, functionKind, functionId, request.filter!)

        if (rows.length === 0) {
            return { queued_count: 0, skipped_count: 0 }
        }

        const maxAttempts = request.filter?.max_attempts
        const queuedInvocations: CyclotronJobInvocation[] = []
        let skipped = 0

        for (const row of rows) {
            // Treat max_attempts as an upper bound on existing attempts. If the
            // invocation has already been retried that many times, don't queue
            // another. The filter-mode query also enforces this in SQL — this
            // is a defensive backstop for the by-IDs path.
            if (maxAttempts !== undefined && row.attempts >= maxAttempts) {
                counterReplayInvocationsSkipped.labels(functionKind, 'over_max_attempts').inc()
                skipped++
                continue
            }

            try {
                const invocation = await this.rehydrateInvocation(teamId, functionKind, functionId, row)
                if (!invocation) {
                    counterReplayInvocationsSkipped.labels(functionKind, 'rehydrate_failed').inc()
                    skipped++
                    continue
                }

                // Lifecycle row marking the replay-start. status='running',
                // is_retry=1, attempts incremented. The matching terminal row
                // is written by the worker when the invocation finishes.
                this.invocationResultsRowsService.queueLifecycleRow(invocation, 'running', { isRetry: true })
                queuedInvocations.push(invocation)
            } catch (e) {
                logger.error('Replay failed to rehydrate invocation', {
                    error: e instanceof Error ? e.message : String(e),
                    invocation_id: row.invocation_id,
                })
                counterReplayInvocationsSkipped.labels(functionKind, 'exception').inc()
                skipped++
            }
        }

        if (queuedInvocations.length > 0) {
            await this.cyclotronJobQueue.queueInvocations(queuedInvocations)
            await this.invocationResultsRowsService.flush()
            counterReplayInvocationsQueued.labels(functionKind).inc(queuedInvocations.length)
        }

        return { queued_count: queuedInvocations.length, skipped_count: skipped }
    }

    private async fetchByIds(
        teamId: number,
        functionKind: ReplayFunctionKind,
        functionId: string,
        ids: string[]
    ): Promise<InvocationRow[]> {
        if (ids.length > HOG_INVOCATION_REPLAY_MAX_COUNT) {
            throw new Error(`At most ${HOG_INVOCATION_REPLAY_MAX_COUNT} invocation_ids per request.`)
        }

        const result = await this.clickhouse.query({
            query: `/* team_id:${teamId} query_type:hog_invocation_replay_by_ids */
                SELECT
                    invocation_id,
                    argMax(parent_run_id, version)      AS parent_run_id,
                    argMax(attempts, version)           AS attempts,
                    argMax(invocation_globals, version) AS invocation_globals
                FROM hog_invocation_results
                WHERE team_id = {team_id:Int64}
                  AND function_kind = {function_kind:String}
                  AND function_id = {function_id:String}
                  AND invocation_id IN {invocation_ids:Array(String)}
                GROUP BY invocation_id
                HAVING argMax(is_deleted, version) = 0`,
            query_params: {
                team_id: teamId,
                function_kind: functionKind,
                function_id: functionId,
                invocation_ids: ids,
            },
            format: 'JSONEachRow',
        })

        return (await result.json()) as InvocationRow[]
    }

    private async fetchByFilter(
        teamId: number,
        functionKind: ReplayFunctionKind,
        functionId: string,
        filter: ReplayFilter
    ): Promise<InvocationRow[]> {
        const status = filter.status?.length ? filter.status : ['failed']
        const maxCount = Math.min(filter.max_count ?? HOG_INVOCATION_REPLAY_MAX_COUNT, HOG_INVOCATION_REPLAY_MAX_COUNT)

        // The HAVING clause does the ReplacingMergeTree collapse + status
        // filter. max_attempts is enforced both here (so we don't carry rows
        // we'll just throw away) and again in `replay()` as a backstop.
        const errorKindClause = filter.error_kind?.length
            ? 'AND argMax(error_kind, version) IN {error_kind:Array(String)}'
            : ''
        const maxAttemptsClause =
            filter.max_attempts !== undefined ? 'AND argMax(attempts, version) < {max_attempts:UInt8}' : ''

        const result = await this.clickhouse.query({
            query: `/* team_id:${teamId} query_type:hog_invocation_replay_by_filter */
                SELECT
                    invocation_id,
                    argMax(parent_run_id, version)      AS parent_run_id,
                    argMax(attempts, version)           AS attempts,
                    argMax(invocation_globals, version) AS invocation_globals,
                    max(scheduled_at)                   AS scheduled_at_max
                FROM hog_invocation_results
                WHERE team_id = {team_id:Int64}
                  AND function_kind = {function_kind:String}
                  AND function_id = {function_id:String}
                  AND scheduled_at >= {window_start:DateTime64}
                  AND scheduled_at <  {window_end:DateTime64}
                GROUP BY invocation_id
                HAVING argMax(is_deleted, version) = 0
                   AND argMax(status, version) IN {status:Array(String)}
                   ${errorKindClause}
                   ${maxAttemptsClause}
                ORDER BY scheduled_at_max DESC, invocation_id DESC
                LIMIT {limit:UInt32}`,
            query_params: {
                team_id: teamId,
                function_kind: functionKind,
                function_id: functionId,
                window_start: filter.window_start,
                window_end: filter.window_end,
                status,
                error_kind: filter.error_kind ?? [],
                max_attempts: filter.max_attempts ?? 255,
                limit: maxCount,
            },
            format: 'JSONEachRow',
        })

        return (await result.json()) as InvocationRow[]
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
                // New cyclotron job id but same logical invocation_id surfaced
                // via the lifecycle row. The row's `invocation_id` is what
                // collapses in ReplacingMergeTree; the cyclotron id can churn.
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
            // For hog flows, `invocation_globals` is the full HogFlowInvocationContext
            // (event, personId, variables, actionStepCount). We rebuild filterGlobals
            // from it on the way through. createHogFlowInvocation expects the
            // upstream globals shape, not the persisted state — so we wrap.
            const state = parsedGlobals as Record<string, any>
            const eventForFilter = state.event ?? {}
            const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal({
                event: eventForFilter,
                person: undefined,
                groups: {},
                variables: state.variables ?? {},
            } as any)

            const invocation: CyclotronJobInvocationHogFlow = createHogFlowInvocation(
                {
                    project: { id: teamId, name: '', url: '' },
                    event: eventForFilter,
                    person: undefined,
                    groups: {},
                    variables: state.variables ?? {},
                    source: { name: '', url: '' },
                } as any,
                hogFlow,
                filterGlobals
            )
            // Preserve the original invocation_id so lifecycle rows collapse
            // against the same key.
            invocation.id = row.invocation_id
            invocation.parentRunId = row.parent_run_id || null
            invocation.state = {
                ...invocation.state!,
                event: eventForFilter,
                actionStepCount: state.actionStepCount ?? 0,
                variables: state.variables ?? {},
            }
            return invocation
        }

        // Suppress unused-import lints when neither branch returns the helper.
        void UUIDT
        return null
    }
}
