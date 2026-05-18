import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiConfig } from 'lib/api'

import { hogql } from '~/queries/utils'

import { hogFunctionsReplayCreate } from 'products/cdp/frontend/generated/api'
import type { HogInvocationReplayFilterStatusEnumApi } from 'products/cdp/frontend/generated/api.schemas'
import { hogFlowsReplayCreate } from 'products/workflows/frontend/generated/api'

import type { hogFunctionRunsV2LogicType } from './hogFunctionRunsV2LogicType'

/**
 * Maximum lifecycle rows we pull from ClickHouse for the list. Tuned against
 * `hog_invocation_results.index_granularity = 1024`; one granule plus headroom
 * keeps the keyset scan cheap while still giving the user a full screen of work.
 */
export const RUNS_V2_PAGE_SIZE = 200

/**
 * Server-side cap on a single replay request, mirrors HOG_INVOCATION_REPLAY_MAX_COUNT
 * in `nodejs/src/cdp/replay/replay-job.types.ts`. Keep them in sync.
 */
export const RUNS_V2_REPLAY_MAX_COUNT = 1000

export type RunStatus = 'running' | 'succeeded' | 'failed'

export type RunsV2FunctionKind = 'hog_function' | 'hog_flow'

export interface HogFunctionRunRow {
    invocation_id: string
    status: RunStatus
    attempts: number
    is_retry: boolean
    error_kind: string
    error_message: string
    scheduled_at: string
    started_at: string | null
    finished_at: string | null
    duration_ms: number | null
    event_uuid: string
    distinct_id: string
    person_id: string
    parent_run_id: string
}

export interface HogFunctionRunsV2Filters {
    date_from: string
    date_to?: string
    status?: RunStatus[]
    error_kind?: string[]
    is_retry?: 'only_retries' | 'only_originals' | undefined
    search?: string
}

export interface HogFunctionRunsV2LogicProps {
    /** HogFunction.id or HogFlow.id */
    id: string
    functionKind: RunsV2FunctionKind
}

const DEFAULT_FILTERS: HogFunctionRunsV2Filters = {
    date_from: '-24h',
    date_to: undefined,
    status: undefined,
    error_kind: undefined,
    is_retry: undefined,
    search: undefined,
}

/**
 * Driving logic for the "Runs" tab — the new per-invocation view backed by
 * `hog_invocation_results`. Pages a HogQL query that collapses lifecycle rows
 * via `argMax(field, version)`, mirroring how `person` is read elsewhere.
 *
 * Replay is asynchronous: the action posts to the cdp-api `/replay` endpoint,
 * which only enqueues a wrapper job onto the cyclotron `replay` queue. The
 * status of that job is not yet surfaced here — the user just sees a toast
 * with the `replay_job_id` and the new rows show up in the list once the
 * worker drains them.
 */
export const hogFunctionRunsV2Logic = kea<hogFunctionRunsV2LogicType>([
    path((id) => ['scenes', 'hog-functions', 'runs-v2', 'hogFunctionRunsV2Logic', id]),
    props({} as HogFunctionRunsV2LogicProps),
    key((props) => `${props.functionKind}:${props.id}`),

    actions({
        setFilters: (filters: Partial<HogFunctionRunsV2Filters>) => ({ filters }),
        resetFilters: true,
        toggleSelected: (invocationId: string) => ({ invocationId }),
        clearSelected: true,
        setExpanded: (invocationId: string, expanded: boolean) => ({ invocationId, expanded }),
        replayInvocations: (invocationIds: string[]) => ({ invocationIds }),
    }),

    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                resetFilters: () => DEFAULT_FILTERS,
            },
        ],
        selectedIds: [
            {} as Record<string, boolean>,
            {
                toggleSelected: (state, { invocationId }) => {
                    const next = { ...state }
                    if (next[invocationId]) {
                        delete next[invocationId]
                    } else {
                        next[invocationId] = true
                    }
                    return next
                },
                clearSelected: () => ({}),
            },
        ],
        expandedIds: [
            {} as Record<string, boolean>,
            {
                setExpanded: (state, { invocationId, expanded }) => {
                    const next = { ...state }
                    if (expanded) {
                        next[invocationId] = true
                    } else {
                        delete next[invocationId]
                    }
                    return next
                },
            },
        ],
    }),

    loaders(({ props, values }) => ({
        runs: [
            [] as HogFunctionRunRow[],
            {
                loadRuns: async (_, breakpoint) => {
                    await breakpoint(100)

                    const { filters } = values
                    const optionalStatusClause = filters.status?.length
                        ? hogql.raw(
                              `AND argMax(status, version) IN (${filters.status.map((s) => `'${s}'`).join(', ')})`
                          )
                        : hogql.raw('')
                    const optionalErrorKindClause = filters.error_kind?.length
                        ? hogql.raw(
                              `AND argMax(error_kind, version) IN (${filters.error_kind
                                  .map((s) => `'${s.replace(/'/g, "\\'")}'`)
                                  .join(', ')})`
                          )
                        : hogql.raw('')
                    // is_retry is stored as 0/1 — convert the UI tristate.
                    const optionalRetryClause =
                        filters.is_retry === 'only_retries'
                            ? hogql.raw('AND argMax(is_retry, version) = 1')
                            : filters.is_retry === 'only_originals'
                              ? hogql.raw('AND argMax(is_retry, version) = 0')
                              : hogql.raw('')
                    // Free-text search hits invocation_id / event_uuid / distinct_id /
                    // person_id. Bloom-filter indexes on event_uuid + function_id
                    // keep this fast for the cardinality we'll see in practice.
                    const trimmedSearch = filters.search?.trim()
                    const optionalSearchClause = trimmedSearch
                        ? hogql.raw(
                              `AND (
                                  invocation_id = '${trimmedSearch.replace(/'/g, "\\'")}'
                                  OR argMax(event_uuid, version) = '${trimmedSearch.replace(/'/g, "\\'")}'
                                  OR argMax(distinct_id, version) = '${trimmedSearch.replace(/'/g, "\\'")}'
                                  OR argMax(person_id, version) = '${trimmedSearch.replace(/'/g, "\\'")}'
                              )`
                          )
                        : hogql.raw('')

                    const query = hogql`
                        SELECT
                            invocation_id,
                            argMax(status, version)         AS status,
                            argMax(attempts, version)       AS attempts,
                            argMax(is_retry, version)       AS is_retry,
                            argMax(error_kind, version)     AS error_kind,
                            argMax(error_message, version)  AS error_message,
                            max(scheduled_at)               AS scheduled_at,
                            argMax(started_at, version)     AS started_at,
                            argMax(finished_at, version)    AS finished_at,
                            argMax(duration_ms, version)    AS duration_ms,
                            argMax(event_uuid, version)     AS event_uuid,
                            argMax(distinct_id, version)    AS distinct_id,
                            argMax(person_id, version)      AS person_id,
                            argMax(parent_run_id, version)  AS parent_run_id
                        FROM posthog.hog_invocation_results
                        WHERE function_kind = ${props.functionKind}
                          AND function_id = ${props.id}
                        GROUP BY invocation_id
                        HAVING argMax(is_deleted, version) = 0
                           ${optionalStatusClause}
                           ${optionalErrorKindClause}
                           ${optionalRetryClause}
                           ${optionalSearchClause}
                        ORDER BY scheduled_at DESC, invocation_id DESC
                        LIMIT ${RUNS_V2_PAGE_SIZE}
                    `

                    const response = await api.queryHogQL(
                        query,
                        { scene: 'HogFunctionRunsV2', productKey: 'pipeline_destinations' },
                        {
                            refresh: 'force_blocking',
                            filtersOverride: {
                                date_from: filters.date_from,
                                date_to: filters.date_to,
                            },
                        }
                    )

                    return (response.results ?? []).map((row): HogFunctionRunRow => {
                        const [
                            invocation_id,
                            status,
                            attempts,
                            is_retry,
                            error_kind,
                            error_message,
                            scheduled_at,
                            started_at,
                            finished_at,
                            duration_ms,
                            event_uuid,
                            distinct_id,
                            person_id,
                            parent_run_id,
                        ] = row as unknown as [
                            string,
                            RunStatus,
                            number,
                            number,
                            string,
                            string,
                            string,
                            string | null,
                            string | null,
                            number | null,
                            string,
                            string,
                            string,
                            string,
                        ]
                        return {
                            invocation_id,
                            status,
                            attempts,
                            is_retry: Boolean(is_retry),
                            error_kind,
                            error_message,
                            scheduled_at,
                            started_at,
                            finished_at,
                            duration_ms,
                            event_uuid,
                            distinct_id,
                            person_id,
                            parent_run_id,
                        }
                    })
                },
            },
        ],
    })),

    selectors({
        statusCounts: [
            (s) => [s.runs],
            (runs): Record<RunStatus, number> => {
                const counts: Record<RunStatus, number> = { running: 0, succeeded: 0, failed: 0 }
                for (const r of runs) {
                    counts[r.status] = (counts[r.status] ?? 0) + 1
                }
                return counts
            },
        ],
        selectedCount: [(s) => [s.selectedIds], (selectedIds) => Object.keys(selectedIds).length],
        canBulkReplay: [
            (s) => [s.selectedCount],
            (selectedCount) => selectedCount > 0 && selectedCount <= RUNS_V2_REPLAY_MAX_COUNT,
        ],
        // For the replay button's status filter — we never want to replay a
        // 'running' row (it's still in flight). The button is disabled for
        // non-terminal rows in the UI; this selector is also used to filter
        // bulk selection down to valid candidates before posting.
        replayableSelectedIds: [
            (s) => [s.selectedIds, s.runs],
            (selectedIds, runs): string[] => {
                const ids = Object.keys(selectedIds)
                if (ids.length === 0) {
                    return []
                }
                const byId = new Map(runs.map((r) => [r.invocation_id, r]))
                return ids.filter((id) => {
                    const row = byId.get(id)
                    // Allow replay if row not loaded (the user has scrolled past
                    // or filtered it out) — the worker enforces its own checks.
                    return !row || row.status !== 'running'
                })
            },
        ],
    }),

    listeners(({ props, actions, values }) => ({
        setFilters: () => {
            actions.loadRuns(null)
        },
        resetFilters: () => {
            actions.loadRuns(null)
        },
        replayInvocations: async ({ invocationIds }) => {
            if (invocationIds.length === 0) {
                lemonToast.warning('Nothing to replay')
                return
            }
            if (invocationIds.length > RUNS_V2_REPLAY_MAX_COUNT) {
                lemonToast.error(`Replay request capped at ${RUNS_V2_REPLAY_MAX_COUNT} invocations per request`)
                return
            }

            const { filters } = values
            // The server requires a window. Use the same window the list is
            // viewing — that way "replay all visible failures" doesn't pull in
            // rows the user isn't looking at.
            const teamId = ApiConfig.getCurrentTeamId()
            const windowStart = filters.date_from
            const windowEnd = filters.date_to ?? new Date().toISOString()

            const requestBody = {
                filter: {
                    window_start: windowStart,
                    window_end: windowEnd,
                    invocation_ids: invocationIds,
                    // Surface the same status filter the list view is using —
                    // the worker re-checks per row before re-enqueueing.
                    status: filters.status as HogInvocationReplayFilterStatusEnumApi[] | undefined,
                },
            }

            try {
                const response =
                    props.functionKind === 'hog_function'
                        ? await hogFunctionsReplayCreate(String(teamId), props.id, requestBody)
                        : await hogFlowsReplayCreate(String(teamId), props.id, requestBody)
                lemonToast.success(
                    `Replay job ${response.replay_job_id.slice(0, 8)}… queued. Updated rows will appear here as the worker drains the job.`
                )
                actions.clearSelected()
            } catch (e: any) {
                lemonToast.error(`Failed to enqueue replay: ${e?.detail ?? e?.message ?? String(e)}`)
            }
        },
    })),
])
