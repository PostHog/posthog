import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'

import { hogql } from '~/queries/utils'

import { hogFunctionsReplayCreate } from 'products/cdp/frontend/generated/api'
import type { HogInvocationReplayFilterStatusEnumApi } from 'products/cdp/frontend/generated/api.schemas'
import { hogFlowsReplayCreate } from 'products/workflows/frontend/generated/api'

import type { hogInvocationsLogicType } from './hogInvocationsLogicType'

/**
 * Maximum lifecycle rows we pull from ClickHouse for the list. Tuned against
 * `hog_invocation_results.index_granularity = 1024`; one granule plus headroom
 * keeps the keyset scan cheap while still giving the user a full screen of work.
 */
export const HOG_INVOCATIONS_PAGE_SIZE = 200

/**
 * Server-side cap on a single replay request, mirrors HOG_INVOCATION_REPLAY_MAX_COUNT
 * in `nodejs/src/cdp/replay/replay-job.types.ts`. Keep them in sync.
 */
export const HOG_INVOCATIONS_REPLAY_MAX_COUNT = 1000

export type RunStatus = 'running' | 'succeeded' | 'failed'

export type HogInvocationsFunctionKind = 'hog_function' | 'hog_flow'

/**
 * Row-kind stamped on the lifecycle row. `_replay` variants flag the wrapper
 * job that drives a bulk re-run — surfaced in the same Invocations list with
 * a different visual treatment and per-row replay disabled.
 */
export type RunRowKind = 'hog_function' | 'hog_flow' | 'hog_function_replay' | 'hog_flow_replay'

export const isReplayWrapperKind = (kind: RunRowKind): boolean =>
    kind === 'hog_function_replay' || kind === 'hog_flow_replay'

const replayWrapperKindFor = (kind: HogInvocationsFunctionKind): RunRowKind =>
    kind === 'hog_flow' ? 'hog_flow_replay' : 'hog_function_replay'

export interface HogInvocationRow {
    invocation_id: string
    function_kind: RunRowKind
    status: RunStatus
    attempts: number
    is_retry: boolean
    error_kind: string
    error_message: string
    /**
     * `scheduled_at` from the **latest** lifecycle row for this invocation —
     * moves on retries because the cyclotron job gets re-scheduled. Use this
     * to see when the invocation was last touched.
     */
    scheduled_at: string
    /**
     * `scheduled_at` from the **earliest** lifecycle row — the original
     * cyclotron schedule time, fixed regardless of retries. Use this to see
     * when the invocation first entered the system.
     */
    first_scheduled_at: string
    started_at: string | null
    finished_at: string | null
    duration_ms: number | null
    event_uuid: string
    distinct_id: string
    person_id: string
    parent_run_id: string
}

/** Which scheduled timestamp drives the list ordering. */
export type RunsOrderBy = 'latest_scheduled' | 'first_scheduled'

export interface HogInvocationsFilters {
    date_from: string
    date_to?: string
    status?: RunStatus[]
    error_kind?: string[]
    is_retry?: 'only_retries' | 'only_originals' | undefined
    search?: string
    /** Defaults to `latest_scheduled` — newest activity first. */
    order_by?: RunsOrderBy
}

export interface HogInvocationsLogicProps {
    /** HogFunction.id or HogFlow.id */
    id: string
    functionKind: HogInvocationsFunctionKind
}

/**
 * Params for the "Re-run" modal — a bulk replay matched by filter rather than
 * by explicit invocation IDs. `date_from` / `date_to` are date-picker strings
 * (relative or ISO); they get resolved through `dateStringToDayJs` before
 * the request hits the API.
 */
export interface BulkReplayParams {
    date_from: string
    date_to?: string
    status?: RunStatus[]
    error_kind?: string[]
    max_count?: number
    max_attempts?: number
}

const DEFAULT_FILTERS: HogInvocationsFilters = {
    date_from: '-24h',
    date_to: undefined,
    status: undefined,
    error_kind: undefined,
    is_retry: undefined,
    search: undefined,
}

/**
 * How long to wait between auto-refreshes while at least one visible row is
 * mid-flight (real invocation or re-run wrapper, doesn't matter — both surface
 * as `status='running'`). Long enough that we don't hammer ClickHouse on a
 * function with constantly-changing state, short enough that the user sees
 * re-run progress without hitting Refresh.
 */
const AUTO_REFRESH_INTERVAL_MS = 5000

const scheduleAutoRefresh = (
    cache: { disposables: { add: (setup: () => () => void, key?: string) => void; dispose?: (key: string) => void } },
    actions: { loadRuns: (payload: null) => void },
    values: { hasRunningRows: boolean }
): void => {
    if (!values.hasRunningRows) {
        // Nothing in flight — let any pending tick expire naturally.
        return
    }
    // `cache.disposables.add` with a key replaces the previous timer if one is
    // already pending, so back-to-back loads don't accumulate ticks. The
    // plugin tears it down on logic unmount and auto-pauses on hidden tabs,
    // which is exactly the behavior we want here.
    cache.disposables.add(() => {
        const timeoutId = setTimeout(() => actions.loadRuns(null), AUTO_REFRESH_INTERVAL_MS)
        return () => clearTimeout(timeoutId)
    }, 'autoRefresh')
}

/**
 * Pulls one page of collapsed lifecycle rows from `hog_invocation_results`.
 * Shared by initial load and "Load more" — only the OFFSET differs.
 */
async function fetchRunsPage(
    props: HogInvocationsLogicProps,
    filters: HogInvocationsFilters,
    offset: number
): Promise<HogInvocationRow[]> {
    // HAVING clauses reference the SELECT aliases below — wrapping the column
    // again as `argMax(status, version)` makes HogQL substitute `status` for
    // its alias (also `argMax(status, version)`) and produce a nested aggregate.
    const optionalStatusClause = filters.status?.length
        ? hogql.raw(`AND status IN (${filters.status.map((s) => `'${s}'`).join(', ')})`)
        : hogql.raw('')
    const optionalErrorKindClause = filters.error_kind?.length
        ? hogql.raw(`AND error_kind IN (${filters.error_kind.map((s) => `'${s.replace(/'/g, "\\'")}'`).join(', ')})`)
        : hogql.raw('')
    // is_retry is stored as 0/1 — convert the UI tristate.
    const optionalRetryClause =
        filters.is_retry === 'only_retries'
            ? hogql.raw('AND is_retry = 1')
            : filters.is_retry === 'only_originals'
              ? hogql.raw('AND is_retry = 0')
              : hogql.raw('')
    // Free-text search hits invocation_id / event_uuid / distinct_id /
    // person_id. Bloom-filter indexes on event_uuid + function_id keep this
    // fast for the cardinality we'll see in practice.
    const trimmedSearch = filters.search?.trim()
    const optionalSearchClause = trimmedSearch
        ? hogql.raw(
              `AND (
                  invocation_id = '${trimmedSearch.replace(/'/g, "\\'")}'
                  OR event_uuid = '${trimmedSearch.replace(/'/g, "\\'")}'
                  OR distinct_id = '${trimmedSearch.replace(/'/g, "\\'")}'
                  OR person_id = '${trimmedSearch.replace(/'/g, "\\'")}'
              )`
          )
        : hogql.raw('')

    // Pull both real invocations and their re-run wrappers — same function_id,
    // wrappers stamped with the `_replay` suffix so the UI can mark them and
    // disable per-row replay. function_kind has to come out of the row so we
    // can branch on it client-side.
    const replayWrapperKind = replayWrapperKindFor(props.functionKind)
    // ORDER BY references the SELECT aliases (`scheduled_at` = latest activity,
    // `first_scheduled_at` = original schedule time). Default is latest first,
    // matching the previous behavior; clicking the column header in the UI
    // flips the filter and re-runs the query.
    const orderClause =
        filters.order_by === 'first_scheduled'
            ? hogql.raw('ORDER BY first_scheduled_at DESC, invocation_id DESC')
            : hogql.raw('ORDER BY scheduled_at DESC, invocation_id DESC')
    const query = hogql`
        SELECT
            invocation_id,
            function_kind                   AS function_kind,
            argMax(status, version)         AS status,
            argMax(attempts, version)       AS attempts,
            argMax(is_retry, version)       AS is_retry,
            argMax(error_kind, version)     AS error_kind,
            argMax(error_message, version)  AS error_message,
            max(scheduled_at)               AS scheduled_at,
            min(scheduled_at)               AS first_scheduled_at,
            argMax(started_at, version)     AS started_at,
            argMax(finished_at, version)    AS finished_at,
            argMax(duration_ms, version)    AS duration_ms,
            argMax(event_uuid, version)     AS event_uuid,
            argMax(distinct_id, version)    AS distinct_id,
            argMax(person_id, version)      AS person_id,
            argMax(parent_run_id, version)  AS parent_run_id
        FROM posthog.hog_invocation_results
        WHERE function_kind IN (${props.functionKind}, ${replayWrapperKind})
          AND function_id = ${props.id}
        GROUP BY invocation_id, function_kind
        HAVING argMax(is_deleted, version) = 0
           ${optionalStatusClause}
           ${optionalErrorKindClause}
           ${optionalRetryClause}
           ${optionalSearchClause}
        ${orderClause}
        LIMIT ${HOG_INVOCATIONS_PAGE_SIZE}
        OFFSET ${offset}
    `

    const response = await api.queryHogQL(
        query,
        { scene: 'HogInvocations', productKey: 'pipeline_destinations' },
        {
            refresh: 'force_blocking',
            filtersOverride: {
                date_from: filters.date_from,
                date_to: filters.date_to,
            },
        }
    )

    return (response.results ?? []).map((row): HogInvocationRow => {
        const [
            invocation_id,
            function_kind,
            status,
            attempts,
            is_retry,
            error_kind,
            error_message,
            scheduled_at,
            first_scheduled_at,
            started_at,
            finished_at,
            duration_ms,
            event_uuid,
            distinct_id,
            person_id,
            parent_run_id,
        ] = row as unknown as [
            string,
            RunRowKind,
            RunStatus,
            number,
            number,
            string,
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
            function_kind,
            status,
            attempts,
            is_retry: Boolean(is_retry),
            error_kind,
            error_message,
            scheduled_at,
            first_scheduled_at,
            started_at,
            finished_at,
            duration_ms,
            event_uuid,
            distinct_id,
            person_id,
            parent_run_id,
        }
    })
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
export const hogInvocationsLogic = kea<hogInvocationsLogicType>([
    path((id) => ['scenes', 'hog-functions', 'invocations', 'hogInvocationsLogic', id]),
    props({} as HogInvocationsLogicProps),
    key((props) => `${props.functionKind}:${props.id}`),

    actions({
        setFilters: (filters: Partial<HogInvocationsFilters>) => ({ filters }),
        resetFilters: true,
        toggleSelected: (invocationId: string) => ({ invocationId }),
        clearSelected: true,
        setExpanded: (invocationId: string, expanded: boolean) => ({ invocationId, expanded }),
        replayInvocations: (invocationIds: string[]) => ({ invocationIds }),
        bulkReplay: (params: BulkReplayParams) => ({ params }),
        setHasMore: (hasMore: boolean) => ({ hasMore }),
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
        hasMore: [
            false,
            {
                setHasMore: (_, { hasMore }) => hasMore,
                // Reset whenever filters or function id change — the old
                // hasMore is meaningless against the new query.
                setFilters: () => false,
                resetFilters: () => false,
            },
        ],
        /**
         * True only until the first successful load completes. Used by the
         * UI to decide whether to dim the whole table vs. just spin the
         * Refresh button — refreshes shouldn't make the list "flash away".
         */
        hasLoadedOnce: [
            false,
            {
                setHasMore: () => true,
            },
        ],
    }),

    loaders(({ props, values, actions }) => ({
        runs: [
            [] as HogInvocationRow[],
            {
                loadRuns: async (_, breakpoint) => {
                    await breakpoint(100)
                    const rows = await fetchRunsPage(props, values.filters, 0)
                    breakpoint()
                    actions.setHasMore(rows.length >= HOG_INVOCATIONS_PAGE_SIZE)
                    return rows
                },
                /**
                 * Append the next page. Uses OFFSET = current row count for
                 * simplicity — fine for the page sizes this view operates at
                 * (a handful of pages of 200), keyset is overkill until the
                 * user starts paging deep enough that OFFSET starts hurting.
                 */
                loadMore: async (_, breakpoint) => {
                    await breakpoint(50)
                    const offset = values.runs.length
                    const newRows = await fetchRunsPage(props, values.filters, offset)
                    breakpoint()
                    actions.setHasMore(newRows.length >= HOG_INVOCATIONS_PAGE_SIZE)
                    return [...values.runs, ...newRows]
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
            (selectedCount) => selectedCount > 0 && selectedCount <= HOG_INVOCATIONS_REPLAY_MAX_COUNT,
        ],
        // For the replay button's status filter — we never want to replay a
        // 'running' row (it's still in flight), and re-run wrappers can't be
        // re-run themselves. The button is disabled in the UI for both cases;
        // this selector is also used to filter bulk selection down to valid
        // candidates before posting.
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
                    return !row || (row.status !== 'running' && !isReplayWrapperKind(row.function_kind))
                })
            },
        ],
        /**
         * True while any currently-visible row is still in flight. Drives the
         * Invocations tab's auto-refresh — a re-run wrapper that's mid-flight
         * will be a `running` row, so this naturally covers both real
         * invocations the user just kicked off and live re-runs.
         */
        hasRunningRows: [(s) => [s.runs], (runs): boolean => runs.some((r) => r.status === 'running')],
    }),

    listeners(({ props, actions, values, cache }) => ({
        setFilters: () => {
            actions.loadRuns(null)
        },
        resetFilters: () => {
            actions.loadRuns(null)
        },
        loadRunsSuccess: () => {
            scheduleAutoRefresh(cache, actions, values)
        },
        loadMoreSuccess: () => {
            scheduleAutoRefresh(cache, actions, values)
        },
        replayInvocations: async ({ invocationIds }) => {
            if (invocationIds.length === 0) {
                lemonToast.warning('Nothing to replay')
                return
            }
            if (invocationIds.length > HOG_INVOCATIONS_REPLAY_MAX_COUNT) {
                lemonToast.error(`Replay request capped at ${HOG_INVOCATIONS_REPLAY_MAX_COUNT} invocations per request`)
                return
            }

            const { filters } = values
            // The server requires a window. Use the same window the list is
            // viewing — that way "replay all visible failures" doesn't pull in
            // rows the user isn't looking at. `filters.date_from` is the same
            // relative-or-absolute string format the date picker emits (e.g.
            // `-24h`), but the replay endpoint expects ISO 8601, so resolve
            // it through the shared helper first.
            const teamId = ApiConfig.getCurrentTeamId()
            const windowStart = (dateStringToDayJs(filters.date_from) ?? dayjs().subtract(24, 'hour')).toISOString()
            const windowEnd = ((filters.date_to ? dateStringToDayJs(filters.date_to) : null) ?? dayjs()).toISOString()

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
        bulkReplay: async ({ params }) => {
            const teamId = ApiConfig.getCurrentTeamId()
            const windowStart = (dateStringToDayJs(params.date_from) ?? dayjs().subtract(24, 'hour')).toISOString()
            const windowEnd = ((params.date_to ? dateStringToDayJs(params.date_to) : null) ?? dayjs()).toISOString()

            const requestBody = {
                filter: {
                    window_start: windowStart,
                    window_end: windowEnd,
                    status: params.status?.length
                        ? (params.status as HogInvocationReplayFilterStatusEnumApi[])
                        : undefined,
                    error_kind: params.error_kind?.length ? params.error_kind : undefined,
                    max_count: params.max_count,
                    max_attempts: params.max_attempts,
                },
            }

            try {
                const response =
                    props.functionKind === 'hog_function'
                        ? await hogFunctionsReplayCreate(String(teamId), props.id, requestBody)
                        : await hogFlowsReplayCreate(String(teamId), props.id, requestBody)
                lemonToast.success(
                    `Re-run job ${response.replay_job_id.slice(0, 8)}… queued. Matching invocations will be re-run in the background.`
                )
            } catch (e: any) {
                lemonToast.error(`Failed to enqueue re-run: ${e?.detail ?? e?.message ?? String(e)}`)
            }
        },
    })),
])
