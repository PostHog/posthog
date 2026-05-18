import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'

import { hogql } from '~/queries/utils'

import { hogFunctionsReplayCreate } from 'products/cdp/frontend/generated/api'
import type { HogInvocationReplayFilterStatusEnumApi } from 'products/cdp/frontend/generated/api.schemas'
import { hogFlowsReplayCreate } from 'products/workflows/frontend/generated/api'

import type { hogInvocationsLogicType } from './hogInvocationsLogicType'

export const HOG_INVOCATIONS_PAGE_SIZE = 200

/** Mirrors HOG_INVOCATION_REPLAY_MAX_COUNT in `nodejs/src/cdp/replay/replay-job.types.ts`. */
export const HOG_INVOCATIONS_REPLAY_MAX_COUNT = 1000

export type RunStatus = 'running' | 'succeeded' | 'failed'

export type HogInvocationsFunctionKind = 'hog_function' | 'hog_flow'

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
    scheduled_at: string
    first_scheduled_at: string
    started_at: string | null
    finished_at: string | null
    duration_ms: number | null
    event_uuid: string
    distinct_id: string
    person_id: string
    parent_run_id: string
}

export type RunsOrderBy = 'latest_scheduled' | 'first_scheduled'

export interface HogInvocationsFilters {
    date_from: string
    date_to?: string
    status?: RunStatus[]
    error_kind?: string[]
    is_retry?: 'only_retries' | 'only_originals' | undefined
    search?: string
    order_by?: RunsOrderBy
}

export interface HogInvocationsLogicProps {
    /** HogFunction.id or HogFlow.id */
    id: string
    functionKind: HogInvocationsFunctionKind
}

export interface SparklineSeries {
    name: RunStatus
    color: string
    values: number[]
}

export interface SparklineData {
    /** ISO timestamps for each bucket. */
    dates: string[]
    series: SparklineSeries[]
}

export interface BulkReplayParams {
    date_from: string
    date_to?: string
    status?: RunStatus[]
    error_kind?: string[]
    max_count?: number
    max_attempts?: number
}

const URL_PARAM_PREFIX = 'inv_'
const URL_PARAMS = {
    date_from: `${URL_PARAM_PREFIX}date_from`,
    date_to: `${URL_PARAM_PREFIX}date_to`,
    status: `${URL_PARAM_PREFIX}status`,
    error_kind: `${URL_PARAM_PREFIX}error_kind`,
    is_retry: `${URL_PARAM_PREFIX}retry`,
    search: `${URL_PARAM_PREFIX}search`,
    order_by: `${URL_PARAM_PREFIX}order`,
} as const

const filtersToSearchParams = (filters: HogInvocationsFilters): Record<string, string | undefined> => ({
    [URL_PARAMS.date_from]: filters.date_from === '-24h' ? undefined : filters.date_from,
    [URL_PARAMS.date_to]: filters.date_to,
    [URL_PARAMS.status]: filters.status?.length ? filters.status.join(',') : undefined,
    [URL_PARAMS.error_kind]: filters.error_kind?.length ? filters.error_kind.join(',') : undefined,
    [URL_PARAMS.is_retry]: filters.is_retry,
    [URL_PARAMS.search]: filters.search,
    [URL_PARAMS.order_by]: filters.order_by === 'first_scheduled' ? undefined : filters.order_by,
})

const searchParamsToFilters = (searchParams: Record<string, string | undefined>): Partial<HogInvocationsFilters> => {
    const next: Partial<HogInvocationsFilters> = {}
    const dateFrom = searchParams[URL_PARAMS.date_from]
    if (dateFrom) {
        next.date_from = dateFrom
    }
    if (searchParams[URL_PARAMS.date_to]) {
        next.date_to = searchParams[URL_PARAMS.date_to]
    }
    const status = searchParams[URL_PARAMS.status]
    if (status) {
        next.status = status.split(',').filter((s): s is RunStatus => ['running', 'succeeded', 'failed'].includes(s))
    }
    const errorKind = searchParams[URL_PARAMS.error_kind]
    if (errorKind) {
        next.error_kind = errorKind.split(',').filter(Boolean)
    }
    const retry = searchParams[URL_PARAMS.is_retry]
    if (retry === 'only_retries' || retry === 'only_originals') {
        next.is_retry = retry
    }
    if (searchParams[URL_PARAMS.search]) {
        next.search = searchParams[URL_PARAMS.search]
    }
    const orderBy = searchParams[URL_PARAMS.order_by]
    if (orderBy === 'first_scheduled' || orderBy === 'latest_scheduled') {
        next.order_by = orderBy
    }
    return next
}

const DEFAULT_FILTERS: HogInvocationsFilters = {
    date_from: '-24h',
    date_to: undefined,
    status: undefined,
    error_kind: undefined,
    is_retry: undefined,
    search: undefined,
    order_by: 'first_scheduled',
}

const AUTO_REFRESH_INTERVAL_MS = 5000

const scheduleAutoRefresh = (
    // Kea types `cache` as `Record<string, any>` upstream — that's where the
    // `disposables` plugin attaches its handle, but the registration is
    // dynamic so the narrow type isn't visible at this call site.
    cache: Record<string, any>,
    actions: { loadRuns: (payload: null) => void },
    values: { hasRunningRows: boolean }
): void => {
    if (!values.hasRunningRows) {
        return
    }
    cache.disposables.add(() => {
        const timeoutId = setTimeout(() => actions.loadRuns(null), AUTO_REFRESH_INTERVAL_MS)
        return () => clearTimeout(timeoutId)
    }, 'autoRefresh')
}

/**
 * Convert a relative date-picker string (`-1h`, `-7d`, `-3w`) to its duration
 * in hours. Can't reuse `dateStringToDayJs` for this — that one anchors
 * relative strings against `startOf('day')`, so `-1h` resolves to "yesterday
 * 23:00", not "1 hour ago". Returns `null` for absolute / unknown shapes.
 */
const RELATIVE_DATE_REGEX = /^-(\d+)([hdwmqy])$/
const parseRelativeHours = (value: string | undefined): number | null => {
    if (!value) {
        return null
    }
    const match = RELATIVE_DATE_REGEX.exec(value)
    if (!match) {
        return null
    }
    const n = parseInt(match[1], 10)
    const hoursPerUnit: Record<string, number> = {
        h: 1,
        d: 24,
        w: 24 * 7,
        m: 24 * 30,
        q: 24 * 90,
        y: 24 * 365,
    }
    return n * (hoursPerUnit[match[2]] ?? 0)
}

const pickSparklineBucketFn = (
    filters: HogInvocationsFilters
): 'toStartOfMinute' | 'toStartOfHour' | 'toStartOfDay' => {
    // Relative `-Nh / -Nd` strings have a known duration without needing to
    // anchor them; use that directly. Falls back to parsing both endpoints
    // when the filter uses absolute ISO timestamps.
    let hours = parseRelativeHours(filters.date_from)
    if (hours === null) {
        const from = dateStringToDayJs(filters.date_from) ?? dayjs().subtract(24, 'hour')
        const to = filters.date_to ? (dateStringToDayJs(filters.date_to) ?? dayjs()) : dayjs()
        hours = to.diff(from, 'hour')
    }
    if (hours < 24) {
        return 'toStartOfMinute'
    }
    if (hours <= 7 * 24) {
        return 'toStartOfHour'
    }
    return 'toStartOfDay'
}

const SPARKLINE_STATUS_COLORS: Record<RunStatus, string> = {
    running: 'warning',
    succeeded: 'success',
    failed: 'danger',
}

async function fetchSparkline(props: HogInvocationsLogicProps, filters: HogInvocationsFilters): Promise<SparklineData> {
    const replayWrapperKind = replayWrapperKindFor(props.functionKind)
    const bucketFn = pickSparklineBucketFn(filters)
    const query = hogql`
        SELECT
            ${hogql.raw(bucketFn)}(first_scheduled_at) AS bucket,
            status,
            count() AS n
        FROM (
            SELECT
                invocation_id,
                argMax(status, version)     AS status,
                min(scheduled_at)           AS first_scheduled_at
            FROM posthog.hog_invocation_results
            WHERE function_kind IN (${props.functionKind}, ${replayWrapperKind})
              AND function_id = ${props.id}
            GROUP BY invocation_id, function_kind
            HAVING argMax(is_deleted, version) = 0
        )
        GROUP BY bucket, status
        ORDER BY bucket
    `
    const response = await api.queryHogQL(
        query,
        { scene: 'HogInvocations', productKey: 'pipeline_destinations' },
        {
            refresh: 'force_blocking',
            filtersOverride: { date_from: filters.date_from, date_to: filters.date_to },
        }
    )

    // Pivot: HogQL returns one row per (bucket, status). The chart wants one
    // series per status, with `values` aligned to a sorted bucket list. We
    // pick up the buckets in the order CH returned them (ORDER BY bucket) and
    // backfill zeros for series-bucket pairs that didn't appear.
    const bucketSet = new Set<string>()
    const cells: Record<string, Record<RunStatus, number>> = {}
    for (const row of response.results ?? []) {
        const [bucket, status, n] = row as unknown as [string, RunStatus, number]
        if (!bucket) {
            continue
        }
        bucketSet.add(bucket)
        cells[bucket] = cells[bucket] ?? { running: 0, succeeded: 0, failed: 0 }
        cells[bucket][status] = Number(n ?? 0)
    }
    const dates = Array.from(bucketSet).sort()
    const buildValues = (status: RunStatus): number[] => dates.map((d) => cells[d]?.[status] ?? 0)
    const series: SparklineSeries[] = (['failed', 'running', 'succeeded'] as RunStatus[]).map((status) => ({
        name: status,
        color: SPARKLINE_STATUS_COLORS[status],
        values: buildValues(status),
    }))
    return { dates, series }
}

async function fetchRunsPage(
    props: HogInvocationsLogicProps,
    filters: HogInvocationsFilters,
    offset: number
): Promise<HogInvocationRow[]> {
    // HAVING clauses reference the SELECT aliases below — wrapping the column
    // again as `argMax(status, version)` makes HogQL substitute `status` for
    // its alias and produce a nested aggregate.
    const optionalStatusClause = filters.status?.length
        ? hogql.raw(`AND status IN (${filters.status.map((s) => `'${s}'`).join(', ')})`)
        : hogql.raw('')
    const optionalErrorKindClause = filters.error_kind?.length
        ? hogql.raw(`AND error_kind IN (${filters.error_kind.map((s) => `'${s.replace(/'/g, "\\'")}'`).join(', ')})`)
        : hogql.raw('')
    const optionalRetryClause =
        filters.is_retry === 'only_retries'
            ? hogql.raw('AND is_retry = 1')
            : filters.is_retry === 'only_originals'
              ? hogql.raw('AND is_retry = 0')
              : hogql.raw('')
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

    const replayWrapperKind = replayWrapperKindFor(props.functionKind)
    // `ORDER BY max(scheduled_at)` is safe only because the SELECT alias isn't
    // named `scheduled_at` — otherwise HogQL substitutes the alias and produces
    // `max(max(scheduled_at))`.
    const orderClause =
        filters.order_by === 'first_scheduled'
            ? hogql.raw('ORDER BY min(scheduled_at) DESC, invocation_id DESC')
            : hogql.raw('ORDER BY max(scheduled_at) DESC, invocation_id DESC')
    const query = hogql`
        SELECT
            invocation_id,
            function_kind                   AS function_kind,
            argMax(status, version)         AS status,
            argMax(attempts, version)       AS attempts,
            argMax(is_retry, version)       AS is_retry,
            argMax(error_kind, version)     AS error_kind,
            argMax(error_message, version)  AS error_message,
            max(scheduled_at)               AS latest_scheduled_at,
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
 * Replay is async — the `/replay` endpoint enqueues a cyclotron wrapper job;
 * new lifecycle rows show up here once the worker drains it.
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
        setSelectedIds: (ids: string[]) => ({ ids }),
        hydratePeople: (personIds: string[]) => ({ personIds }),
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
                setSelectedIds: (_, { ids }) => Object.fromEntries(ids.map((id) => [id, true])),
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
                setFilters: () => false,
                resetFilters: () => false,
            },
        ],
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
        sparkline: [
            null as SparklineData | null,
            {
                loadSparkline: async (_, breakpoint) => {
                    await breakpoint(100)
                    const data = await fetchSparkline(props, values.filters)
                    breakpoint()
                    return data
                },
            },
        ],
        personPropertiesById: [
            {} as Record<string, { properties: Record<string, any>; distinct_ids?: string[] }>,
            {
                hydratePeople: async ({ personIds }, breakpoint) => {
                    const toFetch = personIds.filter((id) => id && !values.personPropertiesById[id])
                    if (toFetch.length === 0) {
                        return values.personPropertiesById
                    }
                    await breakpoint(50)
                    const idList = hogql.raw(toFetch.map((id) => `toUUID('${id}')`).join(','))
                    const query = hogql`
                        SELECT id, properties
                        FROM persons
                        WHERE id IN (${idList})
                    `
                    const response = await api.queryHogQL(query, {
                        scene: 'HogInvocations',
                        productKey: 'pipeline_destinations',
                    })
                    breakpoint()
                    const next = { ...values.personPropertiesById }
                    for (const row of response.results ?? []) {
                        const [id, propsJson] = row as unknown as [string, string]
                        let properties: Record<string, any> = {}
                        try {
                            properties = JSON.parse(propsJson || '{}')
                        } catch {
                            // Malformed JSON — fall back to empty object.
                        }
                        next[id] = { properties }
                    }
                    return next
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
                    // Allow replay if row not loaded — the worker enforces its own checks.
                    return !row || (row.status !== 'running' && !isReplayWrapperKind(row.function_kind))
                })
            },
        ],
        hasRunningRows: [(s) => [s.runs], (runs): boolean => runs.some((r) => r.status === 'running')],
        selectableIds: [
            (s) => [s.runs],
            (runs): string[] =>
                runs
                    .filter((r) => !isReplayWrapperKind(r.function_kind) && r.status !== 'running')
                    .map((r) => r.invocation_id),
        ],
        selectAllState: [
            (s) => [s.selectedIds, s.selectableIds],
            (selectedIds, selectableIds): 'all' | 'some' | 'none' => {
                if (selectableIds.length === 0) {
                    return 'none'
                }
                const selectedCount = selectableIds.filter((id) => selectedIds[id]).length
                if (selectedCount === 0) {
                    return 'none'
                }
                return selectedCount === selectableIds.length ? 'all' : 'some'
            },
        ],
    }),

    listeners(({ props, actions, values, cache }) => ({
        setFilters: () => {
            actions.loadRuns(null)
            actions.loadSparkline(null)
        },
        resetFilters: () => {
            actions.loadRuns(null)
            actions.loadSparkline(null)
        },
        loadRunsSuccess: () => {
            scheduleAutoRefresh(cache, actions, values)
            const personIds = Array.from(new Set(values.runs.map((r) => r.person_id).filter(Boolean)))
            if (personIds.length > 0) {
                actions.hydratePeople(personIds)
            }
        },
        loadMoreSuccess: () => {
            scheduleAutoRefresh(cache, actions, values)
            const personIds = Array.from(new Set(values.runs.map((r) => r.person_id).filter(Boolean)))
            if (personIds.length > 0) {
                actions.hydratePeople(personIds)
            }
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
            const teamId = ApiConfig.getCurrentTeamId()
            const windowStart = (dateStringToDayJs(filters.date_from) ?? dayjs().subtract(24, 'hour')).toISOString()
            const windowEnd = ((filters.date_to ? dateStringToDayJs(filters.date_to) : null) ?? dayjs()).toISOString()

            const requestBody = {
                filter: {
                    window_start: windowStart,
                    window_end: windowEnd,
                    invocation_ids: invocationIds,
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

    actionToUrl(({ values }) => {
        const buildUrl = (): [
            string,
            Record<string, string | undefined>,
            Record<string, string>,
            { replace: true },
        ] => [
            router.values.location.pathname,
            { ...router.values.searchParams, ...filtersToSearchParams(values.filters) },
            router.values.hashParams,
            { replace: true },
        ]
        return {
            setFilters: buildUrl,
            resetFilters: buildUrl,
        }
    }),

    urlToAction(({ actions, values }) => {
        const handleSearch = (_: any, searchParams: Record<string, string | undefined>): void => {
            const next = searchParamsToFilters(searchParams)
            // Diff against current state to avoid looping with actionToUrl.
            const changed = Object.entries(next).some(
                ([key, value]) =>
                    JSON.stringify(value) !== JSON.stringify(values.filters[key as keyof HogInvocationsFilters])
            )
            if (changed) {
                actions.setFilters(next)
            }
        }
        return {
            '*': handleSearch,
        }
    }),
])
