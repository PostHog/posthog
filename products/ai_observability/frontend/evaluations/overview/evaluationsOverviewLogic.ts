import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'
import type { LocationChangedPayload } from 'kea-router/lib/types'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { dateMapping, dateStringToComponents, dateStringToDayJs, startOfWeek } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, type DateMappingOption } from '~/types'

import { evaluationsOverviewRetrieve } from '../../generated/api'
import type {
    AttentionReasonsEnumApi,
    EvaluationDirectoryApi,
    EvaluationResultApi,
    EvaluationsOverviewApi,
    EvaluationsOverviewRetrieveParams,
} from '../../generated/api.schemas'
import { buildEvaluationPassRateTrendsQuery } from '../evaluationPassRateTrendsQuery'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import type { EvaluationDirectoryEditor } from '../llmEvaluationsLogic'
import type { EvaluationConfig } from '../types'
import { type BucketInterval, isChartable, percentValue } from './evaluationOverviewDisplay'

export type OverviewView = 'over_time' | 'by_bucket'
export type OverviewMetric = 'pass_rate' | 'graded' | 'sentiment'
export type AttentionFilter = 'any' | AttentionReasonsEnumApi | null
export type OverviewFailure = 'rate_limited' | 'failed'
export type TableAction = 'edit' | 'enable' | 'disable' | 'move' | 'delete'
export type DirectoryAction = 'rename' | 'delete'

export interface DirectoryTile {
    directory: EvaluationDirectoryApi
    evaluationCount: number
    /** Null until an overview read has covered the directory's evaluations. */
    needAttentionCount: number | null
}

/** Several edits in a row, such as a few moves, reload the overview once. */
const REFRESH_AFTER_CHANGE_MS = 500
/** Several scope picks in a row, such as ticking a few evaluations, read the overview once. */
const SCOPE_CHANGE_DEBOUNCE_MS = 300

/** At or below this many evaluations, the page keeps a way to create another in view. */
const FEW_EVALUATIONS_MAX = 3
/** The longest period people can pick. The backend accepts one day more, for the extra day the runs table counts. */
export const OVERVIEW_MAX_DAYS = 90
/** How many evaluations the chart picks on its first render. People can pick more. */
const DEFAULT_COMPARED = 3

/** A rolling relative start such as "-24h", "-14d" or "-3w", without a Start or End clip. */
const ROLLING_RANGE = /^-(\d+)([hdwmqy])$/
const ROLLING_UNITS = { h: 'hour', d: 'day', w: 'week', m: 'month', q: 'quarter', y: 'year' } as const
/** An exact UTC instant, the format the overview sends an hourly period in. */
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/

/** The date presets the overview can show: everything up to its maximum period. */
export const OVERVIEW_DATE_OPTIONS: DateMappingOption[] = dateMapping.filter((option) => {
    const [value = ''] = option.values
    const days = /^-(\d+)d$/.exec(value)?.[1]
    return value !== 'all' && !(days && Number(days) > OVERVIEW_MAX_DAYS)
})

/** How long the backend caches an overview response. */
const BACKEND_CACHE_MS = 5 * 60 * 1000

/**
 * When an evaluation last changed, on this page or elsewhere such as a save in the editor. The backend caches each
 * scope's results and a change does not alter their cache keys, so every scope read within the cache lifetime skips
 * that cache once, not only the scope on screen.
 */
let lastChangeAt: number | null = null
const refreshedSinceChange = new Set<string>()

function markEveryScopeStale(): void {
    lastChangeAt = Date.now()
    refreshedSinceChange.clear()
}

export function markEvaluationsOverviewStale(): void {
    markEveryScopeStale()
    evaluationsOverviewLogic.findMounted()?.actions.reloadOverview()
}

/** Records that a read for this request skipped the cache, so later reads for it may use the cache again. */
export function markRefreshedAfterChange(requestKey: string): void {
    refreshedSinceChange.add(requestKey)
}

export function resetEvaluationsOverviewStale(): void {
    lastChangeAt = null
    refreshedSinceChange.clear()
}

export function needsRefreshAfterChange(requestKey: string): boolean {
    if (lastChangeAt === null || Date.now() - lastChangeAt > BACKEND_CACHE_MS) {
        return false
    }
    return !refreshedSinceChange.has(requestKey)
}

export interface OverviewPeriod {
    dateFrom: string
    dateTo: string
    /** Length of the period, to check it against the backend's maximum: calendar days for whole days, real time
     * for instants, as the backend counts them. */
    days: number
}

function toInstant(value: dayjs.Dayjs): string {
    return value.utc().format('YYYY-MM-DDTHH:mm:ss[Z]')
}

/** Like `dateStringToDayJs`, but a week clip such as "-1wStart" follows the project's first day of the week. */
function resolveDate(value: string, timezone: string, weekStartDay: number): dayjs.Dayjs | null {
    const components = dateStringToComponents(value)
    if (components?.unit !== 'week' || !components.clip) {
        return dateStringToDayJs(value, timezone)
    }
    const day = dateStringToDayJs(value.replace(/(Start|End)$/, ''), timezone)
    const weekStart = day && startOfWeek(day, weekStartDay)
    return weekStart && (components.clip === 'Start' ? weekStart : weekStart.add(6, 'day'))
}

/**
 * The period to request for the date control's values. A rolling range in hours, like "-24h", is sent as exact
 * instants up to now. Everything else is sent as whole days in the project's timezone, which the backend counts
 * inclusively, so "Last 7 days" is the 7 days ending today. Null when the control has no start.
 */
export function overviewPeriod(
    dateFilter: { dateFrom: string | null; dateTo: string | null },
    timezone: string,
    now: dayjs.Dayjs,
    weekStartDay: number = 0
): OverviewPeriod | null {
    if (!dateFilter.dateFrom || dateFilter.dateFrom === 'all') {
        return null
    }
    // An hourly period comes back as exact instants from an evaluation page, and whole days would widen it.
    if (INSTANT.test(dateFilter.dateFrom) && dateFilter.dateTo && INSTANT.test(dateFilter.dateTo)) {
        const [start, end] = [dayjs.utc(dateFilter.dateFrom), dayjs.utc(dateFilter.dateTo)]
        return { dateFrom: dateFilter.dateFrom, dateTo: dateFilter.dateTo, days: end.diff(start, 'day', true) }
    }
    const rolling = ROLLING_RANGE.exec(dateFilter.dateFrom)
    if (rolling && !dateFilter.dateTo) {
        const unit = ROLLING_UNITS[rolling[2] as keyof typeof ROLLING_UNITS]
        if (unit === 'hour') {
            // Whole minutes keep the request, and so the backend's cache key, stable within a minute.
            const end = now.startOf('minute')
            const start = end.subtract(Number(rolling[1]), unit)
            return { dateFrom: toInstant(start), dateTo: toInstant(end), days: end.diff(start, 'day', true) }
        }
        // The backend counts today as one of the days, so the range starts one day after the same day N units ago.
        const today = now.tz(timezone).startOf('day')
        const start = today.subtract(Number(rolling[1]), unit).add(1, 'day')
        return wholeDays(start, today)
    }
    const start = resolveDate(dateFilter.dateFrom, timezone, weekStartDay)
    const end = (dateFilter.dateTo ? resolveDate(dateFilter.dateTo, timezone, weekStartDay) : null) ?? now.tz(timezone)
    if (!start) {
        return null
    }
    return wholeDays(start, end)
}

function wholeDays(start: dayjs.Dayjs, end: dayjs.Dayjs): OverviewPeriod {
    const dateFrom = start.format('YYYY-MM-DD')
    const dateTo = end.format('YYYY-MM-DD')
    // Counted on UTC dates, because a local day across a daylight saving change is 23 or 25 hours long.
    return { dateFrom, dateTo, days: dayjs.utc(dateTo).diff(dayjs.utc(dateFrom), 'day') + 1 }
}

function matchesAttention(row: EvaluationResultApi, filter: AttentionFilter): boolean {
    if (filter === null) {
        return true
    }
    return filter === 'any' ? row.attentionReasons.length > 0 : row.attentionReasons.includes(filter)
}

// Display order only. A worse result comes before a silent one, because a quality drop is the finding people come
// for, and evaluations that never ran would otherwise push it below the fold.
const ATTENTION_ORDER: Record<AttentionReasonsEnumApi, number> = { errored: 0, worse: 1, silent: 2 }

function attentionRank(row: EvaluationResultApi): number {
    return Math.min(Number.POSITIVE_INFINITY, ...row.attentionReasons.map((reason) => ATTENTION_ORDER[reason]))
}

/**
 * How much worse a row got, larger is worse. A pass rate gets worse as it falls, and sentiment gets worse as its
 * negative share rises.
 */
function worsening(row: EvaluationResultApi): number {
    const change = row.change?.value ?? 0
    return row.summary.kind === 'sentiment' ? change : -change
}

/** Most urgent first: by reason, then the biggest worsening within a reason. */
function compareUrgency(a: EvaluationResultApi, b: EvaluationResultApi): number {
    return attentionRank(a) - attentionRank(b) || worsening(b) - worsening(a)
}

/** Rows that ask for attention first, most urgent first, then the rest as the backend sent them. */
function attentionFirst(rows: EvaluationResultApi[]): EvaluationResultApi[] {
    return rows
        .map((row, index) => ({ row, index }))
        .sort((a, b) => compareUrgency(a.row, b.row) || a.index - b.index)
        .map(({ row }) => row)
}

/**
 * The table's default order: attention first, most urgent first, then running evaluations by graded volume, then
 * disabled ones and ones without results.
 */
function tableOrder(rows: EvaluationResultApi[]): EvaluationResultApi[] {
    const group = (row: EvaluationResultApi): number =>
        row.attentionReasons.length > 0 ? attentionRank(row) : !row.enabled || row.gradedCount === 0 ? 4 : 3
    return [...rows].sort(
        (a, b) =>
            group(a) - group(b) ||
            (group(a) === ATTENTION_ORDER.worse ? worsening(b) - worsening(a) : 0) ||
            b.gradedCount - a.gradedCount
    )
}

function dipCount(row: EvaluationResultApi): number {
    return row.bucketStatus.filter((status) => status === 'dip').length
}

/** Pass rates sort weakest first. Other types have no shared scale, so they sort after them. */
function gridSortRate(row: EvaluationResultApi): number {
    const rate = percentValue(row)
    return row.summary.kind === 'pass_rate' && Number.isFinite(rate) ? rate : 100
}

/** Rate limiting has its own message, because waiting fixes it. */
export function failureOf(error: unknown): OverviewFailure {
    return error instanceof ApiError && error.status === 429 ? 'rate_limited' : 'failed'
}

export interface OverviewRequest {
    params: EvaluationsOverviewRetrieveParams
    /** False when the request would be refused or would not match what the page shows. */
    ready: boolean
    /** Why nothing is requested, for the page to show in place of results. */
    notice: string | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface evaluationsOverviewLogicValues {
    dateFilter: {
        dateFrom: string | null
        dateTo: string | null
    } // llmEvaluationsLogic
    directoryEditor: EvaluationDirectoryEditor | null // llmEvaluationsLogic
    evaluationDirectories: EvaluationDirectoryApi[] // llmEvaluationsLogic
    evaluations: EvaluationConfig[] // llmEvaluationsLogic
    evaluationsLoadFailed: boolean // llmEvaluationsLogic
    evaluationsSettled: boolean // llmEvaluationsLogic
    selectedDirectory: EvaluationDirectoryApi | null // llmEvaluationsLogic
    selectedDirectoryId: string | null // llmEvaluationsLogic
    searchParams: Record<string, any> // router
    currentTeamId: number | null // teamLogic
    timezone: string // teamLogic
    weekStartDay: number // teamLogic
    attentionById: Record<string, boolean>
    attentionCounts: Record<string, number>
    attentionFilter: AttentionFilter
    buckets: string[]
    chartedIds: string[]
    chosenMetric: OverviewMetric
    compareListRows: EvaluationResultApi[]
    comparedIds: string[] | null
    configById: Map<string, EvaluationConfig>
    directoryTiles: DirectoryTile[]
    evaluationListFailed: boolean
    evaluationUrl: (id: string, params?: Record<string, string>) => string
    exploreUrl: string | null
    few: boolean
    interval: BucketInterval
    measuredPassRateRows: EvaluationResultApi[]
    metric: OverviewMetric
    nothingGraded: boolean
    overview: EvaluationsOverviewApi | null
    overviewFailure: OverviewFailure | null
    overviewLoading: boolean
    periodLength: number
    periodNow: number
    pickedIds: string[]
    request: OverviewRequest
    rows: EvaluationResultApi[]
    rowsById: Map<string, EvaluationResultApi>
    scopeEvaluations: EvaluationConfig[]
    scopedIds: string[] | null
    search: string
    sentimentRow: EvaluationResultApi | null
    statusGridRows: EvaluationResultApi[]
    tableRows: EvaluationResultApi[]
    togglingIds: string[]
    view: OverviewView
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface evaluationsOverviewLogicActions {
    deleteDirectory: (id: string) => {
        id: string
    } // llmEvaluationsLogic
    deleteDirectorySuccess: (id: string) => {
        id: string
    } // llmEvaluationsLogic
    deleteEvaluation: (id: string) => {
        id: string
    } // llmEvaluationsLogic
    deleteEvaluationSuccess: (id: string) => {
        id: string
    } // llmEvaluationsLogic
    loadEvaluations: () => {
        value: true
    } // llmEvaluationsLogic
    loadEvaluationsFailure: () => {
        value: true
    } // llmEvaluationsLogic
    loadEvaluationsSuccess: (evaluations: EvaluationConfig[]) => {
        evaluations: EvaluationConfig[]
    } // llmEvaluationsLogic
    moveEvaluation: (
        id: string,
        directoryId: string | null
    ) => {
        directoryId: string | null
        id: string
    } // llmEvaluationsLogic
    moveEvaluationSuccess: (
        id: string,
        directoryId: string | null
    ) => {
        directoryId: string | null
        id: string
    } // llmEvaluationsLogic
    restoreEvaluationSuccess: (evaluation: EvaluationConfig) => {
        evaluation: EvaluationConfig
    } // llmEvaluationsLogic
    selectDirectory: (directoryId: string | null) => {
        directoryId: string | null
    } // llmEvaluationsLogic
    setDates: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    } // llmEvaluationsLogic
    submitDirectory: () => {
        value: true
    } // llmEvaluationsLogic
    submitDirectorySuccess: () => {
        value: true
    } // llmEvaluationsLogic
    toggleEvaluationEnabled: (id: string) => {
        id: string
    } // llmEvaluationsLogic
    toggleEvaluationEnabledFailure: (
        id: string,
        error: string
    ) => {
        error: string
        id: string
    } // llmEvaluationsLogic
    toggleEvaluationEnabledSuccess: (id: string) => {
        id: string
    } // llmEvaluationsLogic
    locationChanged: ({
        method,
        pathname,
        search,
        searchParams,
        hash,
        hashParams,
        initial,
        url,
        routerState,
    }: LocationChangedPayload) => {
        hash: string
        hashParams: Record<string, any>
        initial: boolean
        method: 'POP' | 'PUSH' | 'REPLACE'
        pathname: string
        routerState: Record<string, any>
        search: string
        searchParams: Record<string, any>
        url: string
    } // router
    clickExplore: () => {
        value: true
    }
    loadOverview: (_: void) => void
    loadOverviewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOverviewSuccess: (
        overview: EvaluationsOverviewApi | null,
        payload?: void
    ) => {
        overview: EvaluationsOverviewApi | null
        payload?: void
    }
    openDirectory: (directoryId: string) => {
        directoryId: string
    }
    refreshAfterChange: () => {
        value: true
    }
    reloadOverview: () => {
        value: true
    }
    resetPicks: () => {
        value: true
    }
    retryOverview: () => {
        value: true
    }
    selectCard: (card: OverviewMetric) => {
        card: OverviewMetric
    }
    setAttentionFilter: (filter: AttentionFilter) => {
        filter: AttentionFilter
    }
    setComparedIds: (ids: string[]) => {
        ids: string[]
    }
    setOverviewFailure: (failure: OverviewFailure) => {
        failure: OverviewFailure
    }
    setPickedIds: (ids: string[]) => {
        ids: string[]
    }
    setSearch: (search: string) => {
        search: string
    }
    setView: (view: OverviewView) => {
        view: OverviewView
    }
    toggleCompared: (id: string) => {
        id: string
    }
    trackDirectoryAction: (action: DirectoryAction) => {
        action: DirectoryAction
    }
    trackTableAction: (action: TableAction) => {
        action: TableAction
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface evaluationsOverviewLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        scopeEvaluations: (evaluations: EvaluationConfig[], selectedDirectoryId: string | null) => EvaluationConfig[]
        scopedIds: (
            scopeEvaluations: EvaluationConfig[],
            pickedIds: string[],
            selectedDirectoryId: string | null
        ) => string[] | null
        request: (
            dateFilter: {
                dateFrom: string | null
                dateTo: string | null
            },
            timezone: string,
            weekStartDay: number,
            scopedIds: string[] | null,
            selectedDirectoryId: string | null,
            evaluationsSettled: boolean,
            evaluationsLoadFailed: boolean,
            periodNow: number
        ) => OverviewRequest
        rows: (overview: EvaluationsOverviewApi | null) => EvaluationResultApi[]
        buckets: (overview: EvaluationsOverviewApi | null) => string[]
        interval: (overview: EvaluationsOverviewApi | null) => BucketInterval
        periodLength: (overview: EvaluationsOverviewApi | null) => number
        rowsById: (rows: EvaluationResultApi[]) => Map<string, EvaluationResultApi>
        few: (evaluations: EvaluationConfig[]) => boolean
        nothingGraded: (rows: EvaluationResultApi[]) => boolean
        sentimentRow: (
            overview: EvaluationsOverviewApi | null,
            rowsById: Map<string, EvaluationResultApi>
        ) => EvaluationResultApi | null
        metric: (chosenMetric: OverviewMetric, sentimentRow: EvaluationResultApi | null) => OverviewMetric
        compareListRows: (rows: EvaluationResultApi[], nothingGraded: boolean) => EvaluationResultApi[]
        measuredPassRateRows: (
            overview: EvaluationsOverviewApi | null,
            rowsById: Map<string, EvaluationResultApi>
        ) => EvaluationResultApi[]
        chartedIds: (comparedIds: string[] | null, compareListRows: EvaluationResultApi[]) => string[]
        statusGridRows: (rows: EvaluationResultApi[]) => EvaluationResultApi[]
        configById: (evaluations: EvaluationConfig[]) => Map<string, EvaluationConfig>
        attentionCounts: (rows: EvaluationResultApi[]) => Record<string, number>
        directoryTiles: (
            evaluationDirectories: EvaluationDirectoryApi[],
            evaluations: EvaluationConfig[],
            attentionById: Record<string, boolean>
        ) => DirectoryTile[]
        tableRows: (
            rows: EvaluationResultApi[],
            search: string,
            attentionFilter: AttentionFilter
        ) => EvaluationResultApi[]
        evaluationUrl: (
            searchParams: Record<string, any>,
            request: OverviewRequest
        ) => (id: string, params?: Record<string, string>) => string
        exploreUrl: (
            evaluations: EvaluationConfig[],
            scopedIds: string[] | null,
            request: OverviewRequest,
            interval: BucketInterval,
            rowsById: Map<string, EvaluationResultApi>
        ) => string | null
        evaluationListFailed: (
            evaluationsLoadFailed: boolean,
            overviewFailure: OverviewFailure | null,
            request: OverviewRequest
        ) => boolean
    }
}

export type evaluationsOverviewLogicType = MakeLogicType<
    evaluationsOverviewLogicValues,
    evaluationsOverviewLogicActions,
    Record<string, any>,
    evaluationsOverviewLogicMeta
>

export const evaluationsOverviewLogic = kea<evaluationsOverviewLogicType>([
    path(['products', 'ai_observability', 'frontend', 'evaluations', 'overview', 'evaluationsOverviewLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId', 'timezone', 'weekStartDay'],
            router,
            ['searchParams'],
            llmEvaluationsLogic,
            [
                'dateFilter',
                'evaluations',
                'evaluationsSettled',
                'evaluationsLoadFailed',
                'selectedDirectoryId',
                'selectedDirectory',
                'evaluationDirectories',
                'directoryEditor',
            ],
        ],
        actions: [
            llmEvaluationsLogic,
            [
                'setDates',
                'selectDirectory',
                'loadEvaluations',
                'loadEvaluationsSuccess',
                'loadEvaluationsFailure',
                'toggleEvaluationEnabled',
                'toggleEvaluationEnabledSuccess',
                'toggleEvaluationEnabledFailure',
                'moveEvaluation',
                'deleteEvaluation',
                'moveEvaluationSuccess',
                'deleteEvaluationSuccess',
                'restoreEvaluationSuccess',
                'submitDirectory',
                'submitDirectorySuccess',
                'deleteDirectory',
                'deleteDirectorySuccess',
            ],
            router,
            ['locationChanged'],
        ],
    })),
    actions({
        setPickedIds: (ids: string[]) => ({ ids }),
        setView: (view: OverviewView) => ({ view }),
        selectCard: (card: OverviewMetric) => ({ card }),
        toggleCompared: (id: string) => ({ id }),
        setComparedIds: (ids: string[]) => ({ ids }),
        clickExplore: true,
        setSearch: (search: string) => ({ search }),
        setAttentionFilter: (filter: AttentionFilter) => ({ filter }),
        trackTableAction: (action: TableAction) => ({ action }),
        setOverviewFailure: (failure: OverviewFailure) => ({ failure }),
        refreshAfterChange: true,
        reloadOverview: true,
        retryOverview: true,
        resetPicks: true,
        openDirectory: (directoryId: string) => ({ directoryId }),
        trackDirectoryAction: (action: DirectoryAction) => ({ action }),
    }),
    loaders(({ actions, values, cache }) => ({
        overview: [
            null as EvaluationsOverviewApi | null,
            {
                loadOverview: async (_: void, breakpoint) => {
                    if (!values.currentTeamId || !values.request.ready) {
                        // A refresh can land while the list reloads. The results stay on screen, and a cleared key lets
                        // the load after the list arrives run, with the refresh still pending.
                        cache.requestKey = null
                        // A directory waits for its list. A failed list never arrives, so the page shows its retry instead.
                        if (values.evaluationsLoadFailed) {
                            actions.setOverviewFailure('failed')
                        }
                        return values.request.notice ? null : values.overview
                    }
                    const requestKey = JSON.stringify(values.request)
                    cache.requestKey = requestKey
                    const refresh = needsRefreshAfterChange(requestKey) || cache.forceRefresh === true
                    const requestedAt = performance.now()
                    let overview: EvaluationsOverviewApi
                    try {
                        overview = await evaluationsOverviewRetrieve(String(values.currentTeamId), {
                            ...values.request.params,
                            ...(refresh ? { refresh: true } : {}),
                        })
                    } catch (error) {
                        breakpoint()
                        // The page shows its own failure state with a retry, so the loader's generic toast is skipped.
                        actions.setOverviewFailure(failureOf(error))
                        return null
                    }
                    // Drops a response that a newer scope or date change has superseded.
                    breakpoint()
                    // Only a response that lands consumes the refresh, so a retry after a failure skips the cache too.
                    if (refresh) {
                        refreshedSinceChange.add(requestKey)
                        cache.forceRefresh = false
                    }
                    // pinned: the event name and its properties, because renaming one breaks dashboards.
                    posthog.capture('llma evaluation overview loaded', {
                        load_ms: Math.round(performance.now() - requestedAt),
                        evaluation_count: overview.evaluations.length,
                        buckets: overview.buckets.length,
                        interval: overview.interval,
                    })
                    return overview
                },
            },
        ],
    })),
    reducers({
        // The instant a rolling period ends at. The request selector reads no clock, so a reload or a new scope or
        // range moves this forward to cover what arrived since. Zero until then reads the clock once.
        periodNow: [
            0,
            {
                reloadOverview: () => Date.now(),
                setDates: () => Date.now(),
                selectDirectory: () => Date.now(),
                setPickedIds: () => Date.now(),
                resetPicks: () => Date.now(),
            },
        ],
        // Picks belong to the directory they were made in, so opening another one starts from all of its evaluations.
        pickedIds: [
            [] as string[],
            {
                setPickedIds: (_, { ids }) => ids,
                selectDirectory: () => [],
                resetPicks: () => [],
                deleteEvaluationSuccess: (state, { id }) => state.filter((picked) => picked !== id),
            },
        ],
        view: [
            'over_time' as OverviewView,
            {
                setView: (_, { view }) => view,
                // A metric swaps the over time chart, so it shows that view.
                selectCard: () => 'over_time',
            },
        ],
        chosenMetric: ['pass_rate' as OverviewMetric, { selectCard: (_, { card }) => card }],
        // Null keeps the default picks, so they follow the data until someone picks by hand.
        comparedIds: [
            null as string[] | null,
            {
                setPickedIds: () => null,
                selectDirectory: () => null,
                resetPicks: () => null,
                setComparedIds: (_, { ids }) => ids,
            },
        ],
        overviewFailure: [
            null as OverviewFailure | null,
            {
                loadOverview: () => null,
                setOverviewFailure: (_, { failure }) => failure,
            },
        ],
        search: ['', { setSearch: (_, { search }) => search }],
        // Whether each evaluation needed attention in the latest read that covered it, so directory tiles keep
        // their counts while one directory scopes the overview.
        attentionById: [
            {} as Record<string, boolean>,
            {
                setDates: () => ({}),
                loadOverviewSuccess: (state, { overview }) =>
                    overview
                        ? {
                              ...state,
                              ...Object.fromEntries(
                                  overview.evaluations.map((row) => [row.id, row.attentionReasons.length > 0])
                              ),
                          }
                        : state,
            },
        ],
        attentionFilter: [
            null as AttentionFilter,
            {
                setAttentionFilter: (_, { filter }) => filter,
            },
        ],
        // The enable switch has no in-flight state of its own, so the table tracks it to block a second click.
        togglingIds: [
            [] as string[],
            {
                toggleEvaluationEnabled: (state, { id }) => [...state, id],
                toggleEvaluationEnabledSuccess: (state, { id }) => state.filter((other) => other !== id),
                toggleEvaluationEnabledFailure: (state, { id }) => state.filter((other) => other !== id),
            },
        ],
    }),
    selectors({
        scopeEvaluations: [
            (s) => [s.evaluations, s.selectedDirectoryId],
            (evaluations: EvaluationConfig[], selectedDirectoryId: string | null): EvaluationConfig[] =>
                selectedDirectoryId
                    ? evaluations.filter((evaluation) => evaluation.directory_id === selectedDirectoryId)
                    : evaluations,
        ],
        // Null covers every evaluation the user can see.
        scopedIds: [
            (s) => [s.scopeEvaluations, s.pickedIds, s.selectedDirectoryId],
            (
                scopeEvaluations: EvaluationConfig[],
                pickedIds: string[],
                selectedDirectoryId: string | null
            ): string[] | null => {
                const inScope = new Set(scopeEvaluations.map((evaluation) => evaluation.id))
                const picked = selectedDirectoryId ? pickedIds.filter((id) => inScope.has(id)) : pickedIds
                if (picked.length > 0) {
                    return picked
                }
                return selectedDirectoryId ? [...inScope] : null
            },
        ],
        request: [
            (s) => [
                s.dateFilter,
                s.timezone,
                s.weekStartDay,
                s.scopedIds,
                s.selectedDirectoryId,
                s.evaluationsSettled,
                s.evaluationsLoadFailed,
                s.periodNow,
            ],
            (
                dateFilter: {
                    dateFrom: string | null
                    dateTo: string | null
                },
                timezone: string,
                weekStartDay: number,
                scopedIds: string[] | null,
                selectedDirectoryId: string | null,
                evaluationsSettled: boolean,
                evaluationsLoadFailed: boolean,
                periodNow: number
            ): OverviewRequest => {
                const period = overviewPeriod(
                    dateFilter,
                    timezone,
                    periodNow ? dayjs(periodNow) : dayjs(),
                    weekStartDay
                )
                const params: EvaluationsOverviewRetrieveParams = {
                    date_from: period?.dateFrom,
                    date_to: period?.dateTo,
                    evaluation_ids: scopedIds ?? undefined,
                }
                // Without a start the backend falls back to its default period, which the date control would not show.
                if (!period || period.days > OVERVIEW_MAX_DAYS) {
                    return {
                        params,
                        ready: false,
                        notice: `Pick a range of ${OVERVIEW_MAX_DAYS} days or less to see results here.`,
                    }
                }
                // A directory's evaluations are only known once the list has loaded. A failed list is not an empty one.
                if (selectedDirectoryId && (!evaluationsSettled || evaluationsLoadFailed)) {
                    return { params, ready: false, notice: null }
                }
                // An empty id list would mean every evaluation, not none.
                if (scopedIds?.length === 0) {
                    return { params, ready: false, notice: 'This directory has no evaluations yet.' }
                }
                return { params, ready: true, notice: null }
            },
        ],
        rows: [
            (s) => [s.overview],
            (overview: EvaluationsOverviewApi | null): EvaluationResultApi[] => overview?.evaluations ?? [],
        ],
        buckets: [(s) => [s.overview], (overview: EvaluationsOverviewApi | null): string[] => overview?.buckets ?? []],
        interval: [
            (s) => [s.overview],
            (overview: EvaluationsOverviewApi | null): BucketInterval => overview?.interval ?? 'day',
        ],
        // The period's length in the interval's unit, for captions. Buckets can start before the period, so their
        // count can be one more than this.
        periodLength: [
            (s) => [s.overview],
            (overview: EvaluationsOverviewApi | null): number =>
                overview
                    ? Math.round(
                          dayjs(overview.end).diff(
                              dayjs(overview.start),
                              overview.interval === 'hour' ? 'hour' : 'day',
                              true
                          )
                      )
                    : 0,
        ],
        rowsById: [
            (s) => [s.rows],
            (rows: EvaluationResultApi[]): Map<string, EvaluationResultApi> =>
                new Map(rows.map((row) => [row.id, row])),
        ],
        few: [
            (s) => [s.evaluations],
            // The create slot is a nudge, so people who can't create evaluations don't see it.
            (evaluations: EvaluationConfig[]): boolean =>
                evaluations.length <= FEW_EVALUATIONS_MAX &&
                !getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor),
        ],
        nothingGraded: [
            (s) => [s.rows],
            (rows: EvaluationResultApi[]): boolean => rows.every((row) => row.gradedCount === 0),
        ],
        sentimentRow: [
            (s) => [s.overview, s.rowsById],
            (
                overview: EvaluationsOverviewApi | null,
                rowsById: Map<string, EvaluationResultApi>
            ): EvaluationResultApi | null => {
                const id = overview?.totals.sentiment?.evaluationId
                return (id && rowsById.get(id)) || null
            },
        ],
        // A scope or period without sentiment results falls back to pass rates, so the chart never mixes the two.
        metric: [
            (s) => [s.chosenMetric, s.sentimentRow],
            (chosenMetric: OverviewMetric, sentimentRow: EvaluationResultApi | null): OverviewMetric =>
                chosenMetric === 'sentiment' && !sentimentRow ? 'pass_rate' : chosenMetric,
        ],
        compareListRows: [
            (s) => [s.rows, s.nothingGraded],
            (rows: EvaluationResultApi[], nothingGraded: boolean): EvaluationResultApi[] => {
                const listed = nothingGraded
                    ? rows
                    : rows.filter((row) => row.attentionReasons.length > 0 || row.gradedCount > 0)
                // Rows with a line to draw come first, so evaluations that never ran do not push them down.
                return [
                    ...attentionFirst(listed.filter(isChartable)),
                    ...attentionFirst(listed.filter((row) => !isChartable(row))),
                ]
            },
        ],
        // Pass rates with enough results to rely on, the ones the median and the chart's background lines use.
        measuredPassRateRows: [
            (s) => [s.overview, s.rowsById],
            (
                overview: EvaluationsOverviewApi | null,
                rowsById: Map<string, EvaluationResultApi>
            ): EvaluationResultApi[] =>
                (overview?.passRateOverview.entries ?? []).flatMap((entry) => {
                    const row = !entry.lowEvidence && rowsById.get(entry.evaluationId)
                    return row ? [row] : []
                }),
        ],
        chartedIds: [
            (s) => [s.comparedIds, s.compareListRows],
            (comparedIds: string[] | null, compareListRows: EvaluationResultApi[]): string[] => {
                if (comparedIds) {
                    return comparedIds
                }
                const chartable = compareListRows.filter(isChartable)
                const urgent = chartable.filter((row) => row.attentionReasons.length > 0).sort(compareUrgency)
                const picked = urgent.length > 0 ? urgent : chartable.sort((a, b) => b.gradedCount - a.gradedCount)
                return picked.slice(0, DEFAULT_COMPARED).map((row) => row.id)
            },
        ],
        // Evaluations with the most unusual days come first. Ones without results go last.
        statusGridRows: [
            (s) => [s.rows],
            (rows: EvaluationResultApi[]): EvaluationResultApi[] =>
                [...rows].sort(
                    (a, b) =>
                        Number(a.gradedCount === 0) - Number(b.gradedCount === 0) ||
                        dipCount(b) - dipCount(a) ||
                        gridSortRate(a) - gridSortRate(b)
                ),
        ],
        configById: [
            (s) => [s.evaluations],
            (evaluations: EvaluationConfig[]): Map<string, EvaluationConfig> =>
                new Map(evaluations.map((evaluation) => [evaluation.id, evaluation])),
        ],
        attentionCounts: [
            (s) => [s.rows],
            (rows: EvaluationResultApi[]): Record<string, number> =>
                Object.fromEntries(
                    (['all', 'any', 'errored', 'silent', 'worse'] as const).map((filter) => [
                        filter,
                        rows.filter((row) => matchesAttention(row, filter === 'all' ? null : filter)).length,
                    ])
                ),
        ],
        directoryTiles: [
            (s) => [s.evaluationDirectories, s.evaluations, s.attentionById],
            (
                directories: EvaluationDirectoryApi[],
                evaluations: EvaluationConfig[],
                attentionById: Record<string, boolean>
            ): DirectoryTile[] =>
                directories.map((directory) => {
                    const members = evaluations.filter((evaluation) => evaluation.directory_id === directory.id)
                    const known = members.every((evaluation) => evaluation.id in attentionById)
                    return {
                        directory,
                        evaluationCount: members.length,
                        needAttentionCount: known
                            ? members.filter((evaluation) => attentionById[evaluation.id]).length
                            : null,
                    }
                }),
        ],
        tableRows: [
            (s) => [s.rows, s.search, s.attentionFilter],
            (rows: EvaluationResultApi[], search: string, attentionFilter: AttentionFilter): EvaluationResultApi[] => {
                const query = search.trim().toLowerCase()
                const matching = rows.filter(
                    (row) => matchesAttention(row, attentionFilter) && row.name.toLowerCase().includes(query)
                )
                return tableOrder(matching)
            },
        ],
        // Links keep the page's search params, so an evaluation returns to this directory. They carry the period the
        // overview resolved, because the evaluation page reads a relative range such as "-7d" with one more day.
        evaluationUrl: [
            (s) => [s.searchParams, s.request],
            (
                searchParams: Record<string, any>,
                request: OverviewRequest
            ): ((id: string, params?: Record<string, string>) => string) => {
                const { date_from, date_to } = request.params
                const period = date_from && date_to ? { date_from, date_to } : {}
                return (id, params = {}) =>
                    combineUrl(urls.aiObservabilityEvaluation(id), { ...searchParams, ...period, ...params }).url
            },
        ],
        exploreUrl: [
            (s) => [s.evaluations, s.scopedIds, s.request, s.interval, s.rowsById],
            (
                evaluations: EvaluationConfig[],
                scopedIds: string[] | null,
                request: OverviewRequest,
                interval: BucketInterval,
                rowsById: Map<string, EvaluationResultApi>
            ): string | null => {
                if (!request.ready) {
                    return null
                }
                // Paused evaluations with results in the period count, as they do on the overview chart.
                const scoped = evaluations.filter(
                    (evaluation) =>
                        (!scopedIds || scopedIds.includes(evaluation.id)) &&
                        (evaluation.enabled || (rowsById.get(evaluation.id)?.gradedCount ?? 0) > 0)
                )
                const { date_from = null, date_to = null } = request.params
                // Trends reads a date-only end as that day's midnight when it buckets by hour, so the day gets an end.
                const dateTo =
                    interval === 'hour' && date_to && /^\d{4}-\d{2}-\d{2}$/.test(date_to)
                        ? `${date_to}T23:59:59`
                        : date_to
                // The period and interval the overview resolved, so the insight covers what the chart it opens from shows.
                const source = buildEvaluationPassRateTrendsQuery(scoped, { dateFrom: date_from, dateTo }, interval)
                if (!source) {
                    return null
                }
                const query: InsightVizNode = { kind: NodeKind.InsightVizNode, source }
                return urls.insightNew({ query })
            },
        ],
        // Results can load without the list, but row actions and the scope picker need it. When the results fail
        // too, their own banner retries both.
        evaluationListFailed: [
            (s) => [s.evaluationsLoadFailed, s.overviewFailure, s.request],
            (
                evaluationsLoadFailed: boolean,
                overviewFailure: OverviewFailure | null,
                request: OverviewRequest
            ): boolean => evaluationsLoadFailed && !overviewFailure && !request.notice,
        ],
    }),
    listeners(({ actions, values, cache }) => {
        // Scope and dates reach this logic through several actions and the URL, so one change can arrive twice.
        const refresh = (): void => {
            const key = JSON.stringify(values.request)
            if (key !== cache.requestKey) {
                cache.requestKey = key
                actions.loadOverview()
            }
        }
        // pinned: every analytics event name and property in these listeners, because renaming one breaks dashboards.
        return {
            setPickedIds: async ({ ids }, breakpoint) => {
                posthog.capture('llma evaluation overview scope changed', {
                    evaluation_count: ids.length,
                    directory_scoped: values.selectedDirectoryId !== null,
                    trigger: 'picker',
                })
                await breakpoint(SCOPE_CHANGE_DEBOUNCE_MS)
                refresh()
            },
            selectDirectory: ({ directoryId }) => {
                posthog.capture('llma evaluation overview scope changed', {
                    evaluation_count: values.scopedIds?.length ?? values.evaluations.length,
                    directory_scoped: directoryId !== null,
                    trigger: 'directory',
                })
                refresh()
            },
            setDates: refresh,
            locationChanged: () => {
                // Browser back and forward change the directory without `selectDirectory`, so picks reset here too.
                if (values.selectedDirectoryId !== cache.directoryId) {
                    cache.directoryId = values.selectedDirectoryId
                    actions.resetPicks()
                }
                refresh()
            },
            loadEvaluationsSuccess: refresh,
            loadEvaluationsFailure: () => {
                // A load that waited for the list has no list to resume with, so the page shows its retry.
                if (cache.requestKey === null) {
                    actions.setOverviewFailure('failed')
                }
            },
            setView: ({ view }) => {
                posthog.capture('llma evaluation overview view changed', { view })
            },
            selectCard: ({ card }) => {
                posthog.capture('llma evaluation overview card clicked', { card })
            },
            toggleCompared: ({ id }) => {
                const current = values.chartedIds
                actions.setComparedIds(
                    current.includes(id) ? current.filter((other) => other !== id) : [...current, id]
                )
            },
            setAttentionFilter: ({ filter }) => {
                posthog.capture('llma evaluation overview attention filter changed', {
                    filter: filter ?? 'all',
                    trigger: 'table',
                })
            },
            trackTableAction: ({ action }) => {
                posthog.capture('llma evaluation overview table action used', { action })
            },
            toggleEvaluationEnabled: ({ id }) => {
                actions.trackTableAction(values.configById.get(id)?.enabled ? 'disable' : 'enable')
            },
            moveEvaluation: () => actions.trackTableAction('move'),
            toggleEvaluationEnabledSuccess: () => actions.refreshAfterChange(),
            moveEvaluationSuccess: () => actions.refreshAfterChange(),
            deleteEvaluationSuccess: () => actions.refreshAfterChange(),
            deleteDirectorySuccess: () => actions.refreshAfterChange(),
            restoreEvaluationSuccess: () => actions.refreshAfterChange(),
            refreshAfterChange: async (_, breakpoint) => {
                markEveryScopeStale()
                await breakpoint(REFRESH_AFTER_CHANGE_MS)
                actions.reloadOverview()
            },
            reloadOverview: () => {
                cache.forceRefresh = true
                actions.loadOverview()
            },
            retryOverview: () => {
                // A directory's overview waits for its list, so a failed list reloads too. Its success resumes the load.
                if (values.evaluationsLoadFailed) {
                    actions.loadEvaluations()
                }
                // A failed list alone leaves the results current, so they load again only when they failed.
                if (values.overviewFailure) {
                    actions.loadOverview()
                }
            },
            openDirectory: ({ directoryId }) => {
                posthog.capture('llma evaluation overview directory opened', {
                    evaluation_count: values.evaluations.filter((evaluation) => evaluation.directory_id === directoryId)
                        .length,
                })
                actions.selectDirectory(directoryId)
            },
            submitDirectory: () => {
                cache.directoryEditorMode = values.directoryEditor?.mode ?? null
            },
            submitDirectorySuccess: () => {
                if (cache.directoryEditorMode === 'create') {
                    posthog.capture('llma evaluation overview directory created')
                } else if (cache.directoryEditorMode === 'rename') {
                    actions.trackDirectoryAction('rename')
                    // Rows carry their directory's name, which the request key does not change with.
                    actions.refreshAfterChange()
                }
            },
            deleteDirectory: () => actions.trackDirectoryAction('delete'),
            trackDirectoryAction: ({ action }) => {
                posthog.capture('llma evaluation overview directory action', { action })
            },
            deleteEvaluation: () => actions.trackTableAction('delete'),
            clickExplore: () => {
                posthog.capture('llma evaluation overview explore clicked', {
                    evaluation_count: values.rows.length,
                })
            },
        }
    }),
    afterMount(({ actions, values, cache }) => {
        cache.directoryId = values.selectedDirectoryId
        cache.requestKey = JSON.stringify(values.request)
        actions.loadOverview()
    }),
])
