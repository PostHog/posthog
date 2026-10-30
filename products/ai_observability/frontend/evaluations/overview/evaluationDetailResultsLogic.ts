import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils/dom'
import { teamLogic } from 'scenes/teamLogic'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { DateRange, NodeKind, TrendsQuery, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { escapeHogQLString, escapePropertyAsHogQLIdentifier } from '~/queries/utils'
import { HogQLMathType, type HogQLPropertyFilter, PropertyFilterType } from '~/types'

import { evaluationsOverviewRetrieve } from '../../generated/api'
import type { EvaluationResultApi, EvaluationsOverviewRetrieveParams } from '../../generated/api.schemas'
import type { EvaluationsOverviewIntervalEnumApi } from '../../generated/api.schemas'
import { evaluationGradedHogQL } from '../constants'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationConfig } from '../types'
import { type BucketInterval, bucketDateRange } from './evaluationOverviewDisplay'
import { type DetailsLoad, fetchEvaluationDetails } from './evaluationResultDrawerLogic'
import type { TrendBreakdownSeries } from './EvaluationResultTrendChart'
import {
    OVERVIEW_MAX_DAYS,
    type OverviewFailure,
    type OverviewRequest,
    failureOf,
    markRefreshedAfterChange,
    needsRefreshAfterChange,
    overviewPeriod,
} from './evaluationsOverviewLogic'

export interface EvaluationDetailResultsLogicProps {
    evaluationId: string
}

/** How many values get their own line. The rest share one "Other" line. */
const BREAKDOWN_LIMIT = 5
/**
 * How many values the query returns. Trends ranks each series on its own and sums the rest into its "Other", which
 * is wrong for a rate, so the top values and "Other" come from these instead.
 */
// ponytail: values past this cap drop out of "Other"; query the counts with HogQL if properties get that wide.
const BREAKDOWN_QUERY_LIMIT = 100
const BREAKDOWN_NULL = '$$_posthog_breakdown_null_$$'
const BREAKDOWN_OTHER = '$$_posthog_breakdown_other_$$'
/** Trends cuts a breakdown value to this length. */
const BREAKDOWN_VALUE_MAX_LENGTH = 400
/** A rolling range of whole days, weeks, months, quarters or years. */
const ROLLING_DAYS = /^-\d+[dwmqy]$/

/** The key trends gives a bucket: the day, or the day and hour, in the project's time zone. */
function trendsBucketKey(bucket: string, interval: BucketInterval): string {
    return interval === 'hour' ? `${bucket.slice(0, 10)} ${bucket.slice(11, 19)}` : bucket.slice(0, 10)
}

interface BreakdownCounts {
    result?: number[]
    graded?: number[]
    days: string[]
}

/** Each breakdown value's result and graded count per bucket. */
function breakdownCounts(response: TrendsQueryResponse): Map<string, BreakdownCounts> {
    const byValue = new Map<string, BreakdownCounts>()
    for (const entry of response.results ?? []) {
        const raw = Array.isArray(entry.breakdown_value) ? entry.breakdown_value[0] : entry.breakdown_value
        const key = String(raw ?? BREAKDOWN_NULL)
        const current: BreakdownCounts = byValue.get(key) ?? { days: entry.days ?? [] }
        current[entry.order === 1 ? 'graded' : 'result'] = entry.data ?? []
        byValue.set(key, current)
    }
    return byValue
}

/** The breakdown query, limited to the given values, so each series returns all of them. */
function restrictBreakdown(query: TrendsQuery, values: string[]): TrendsQuery {
    const property = String(query.breakdownFilter?.breakdowns?.[0]?.property ?? '')
    // The same value Trends breaks down by, so the keys it returned match.
    const value = `ifNull(nullIf(left(toString(properties.${escapePropertyAsHogQLIdentifier(property)}), ${BREAKDOWN_VALUE_MAX_LENGTH}), ''), ${escapeHogQLString(BREAKDOWN_NULL)})`
    const filter: HogQLPropertyFilter = {
        type: PropertyFilterType.HogQL,
        key: `${value} IN (${values.map(escapeHogQLString).join(', ')})`,
    }
    return {
        ...query,
        series: query.series.map((series) => ({ ...series, properties: [...(series.properties ?? []), filter] })),
    }
}

/**
 * The values with the most graded runs keep their own line, and the rest share an "Other" line. A result is a share or
 * a mean of the graded runs, so the "Other" result weighs each value's result by its graded count.
 */
export function topBreakdownSeries(series: TrendBreakdownSeries[], limit: number): TrendBreakdownSeries[] {
    const total = (entry: TrendBreakdownSeries): number => entry.graded.reduce((sum, count) => sum + count, 0)
    const ranked = series.filter((entry) => total(entry) > 0).sort((a, b) => total(b) - total(a))
    const rest = ranked.slice(limit)
    if (rest.length === 0) {
        return ranked
    }
    const graded = rest[0].graded.map((_, bucket) => rest.reduce((sum, entry) => sum + entry.graded[bucket], 0))
    const values = graded.map((count, bucket) =>
        count === 0
            ? NaN
            : rest.reduce(
                  (sum, entry) => sum + (entry.graded[bucket] > 0 ? entry.values[bucket] * entry.graded[bucket] : 0),
                  0
              ) / count
    )
    return [...ranked.slice(0, limit), { key: BREAKDOWN_OTHER, label: 'Other', values, graded }]
}

export interface EvaluationDetailResults {
    row: EvaluationResultApi | null
    buckets: string[]
    interval: BucketInterval
    /** Whether this load skipped the backend's cache, so the loads that follow it skip it too. */
    skippedCache: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface evaluationDetailResultsLogicValues {
    originalEvaluation: EvaluationConfig | null // llmEvaluationLogic
    runsDateRange: DateRange // llmEvaluationLogic
    trendsQuery: TrendsQuery | null // llmEvaluationLogic
    currentTeamId: number | null // teamLogic
    timezone: string // teamLogic
    weekStartDay: number // teamLogic
    breakdownFailure: OverviewFailure | null
    breakdownProperty: string | null
    breakdownQuery: TrendsQuery | null
    breakdownSeries: TrendBreakdownSeries[] | null
    breakdownSeriesLoading: boolean
    details: DetailsLoad | null
    detailsLoading: boolean
    failure: OverviewFailure | null
    periodNow: number
    request: OverviewRequest
    results: EvaluationDetailResults | null
    resultsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface evaluationDetailResultsLogicActions {
    refreshEvaluationRuns: () => {
        value: true
    } // llmEvaluationLogic
    setActiveTab: (tab: string) => {
        tab: string
    } // llmEvaluationLogic
    setRunsDates: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    } // llmEvaluationLogic
    loadBreakdown: (refresh?: boolean) => boolean
    loadBreakdownFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadBreakdownSuccess: (
        breakdownSeries: TrendBreakdownSeries[] | null,
        payload?: boolean
    ) => {
        breakdownSeries: TrendBreakdownSeries[] | null
        payload?: boolean
    }
    loadDetails: (refresh?: boolean) => boolean
    loadDetailsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDetailsSuccess: (
        details: DetailsLoad | null,
        payload?: boolean
    ) => {
        details: DetailsLoad | null
        payload?: boolean
    }
    loadResults: (refresh?: boolean) => boolean
    loadResultsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadResultsSuccess: (
        results: {
            buckets: string[]
            interval: EvaluationsOverviewIntervalEnumApi
            row: EvaluationResultApi | null
            skippedCache: boolean
        } | null,
        payload?: boolean
    ) => {
        results: {
            buckets: string[]
            interval: EvaluationsOverviewIntervalEnumApi
            row: EvaluationResultApi | null
            skippedCache: boolean
        } | null
        payload?: boolean
    }
    runOnPastData: () => {
        value: true
    }
    selectBucket: (bucket: string) => {
        bucket: string
    }
    setBreakdownFailure: (failure: OverviewFailure | null) => {
        failure: OverviewFailure | null
    }
    setBreakdownProperty: (property: string | null) => {
        property: string | null
    }
    setFailure: (failure: OverviewFailure | null) => {
        failure: OverviewFailure | null
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface evaluationDetailResultsLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        breakdownQuery: (
            trendsQuery: TrendsQuery | null,
            originalEvaluation: EvaluationConfig | null,
            breakdownProperty: string | null,
            request: OverviewRequest,
            results: EvaluationDetailResults | null
        ) => TrendsQuery | null
        request: (
            runsDateRange: DateRange,
            timezone: string,
            weekStartDay: number,
            periodNow: number,
            arg: any
        ) => OverviewRequest
    }
}

export type evaluationDetailResultsLogicType = MakeLogicType<
    evaluationDetailResultsLogicValues,
    evaluationDetailResultsLogicActions,
    EvaluationDetailResultsLogicProps,
    evaluationDetailResultsLogicMeta
>

export const evaluationDetailResultsLogic = kea<evaluationDetailResultsLogicType>([
    path((key) => [
        'products',
        'ai_observability',
        'frontend',
        'evaluations',
        'overview',
        'evaluationDetailResultsLogic',
        key,
    ]),
    props({} as EvaluationDetailResultsLogicProps),
    key((props) => props.evaluationId),
    connect((props: EvaluationDetailResultsLogicProps) => ({
        values: [
            llmEvaluationLogic({ evaluationId: props.evaluationId }),
            ['runsDateRange', 'trendsQuery', 'originalEvaluation'],
            teamLogic,
            ['currentTeamId', 'timezone', 'weekStartDay'],
        ],
        actions: [
            llmEvaluationLogic({ evaluationId: props.evaluationId }),
            ['setRunsDates', 'setActiveTab', 'refreshEvaluationRuns'],
        ],
    })),
    actions({
        setFailure: (failure: OverviewFailure | null) => ({ failure }),
        setBreakdownFailure: (failure: OverviewFailure | null) => ({ failure }),
        selectBucket: (bucket: string) => ({ bucket }),
        runOnPastData: true,
        setBreakdownProperty: (property: string | null) => ({ property }),
    }),
    loaders(({ values, props, actions, cache }) => ({
        results: [
            null as EvaluationDetailResults | null,
            {
                loadResults: async (refresh: boolean = false, breakpoint) => {
                    const { request } = values
                    if (!values.currentTeamId || !request.ready) {
                        return null
                    }
                    const requestKey = JSON.stringify(request)
                    const skipCache = refresh || needsRefreshAfterChange(requestKey)
                    try {
                        const overview = await evaluationsOverviewRetrieve(String(values.currentTeamId), {
                            ...request.params,
                            ...(skipCache ? { refresh: true } : {}),
                        })
                        breakpoint()
                        if (skipCache) {
                            markRefreshedAfterChange(requestKey)
                        }
                        return {
                            row: overview.evaluations.find((row) => row.id === props.evaluationId) ?? null,
                            buckets: overview.buckets,
                            interval: overview.interval,
                            skippedCache: skipCache,
                        }
                    } catch (error) {
                        breakpoint()
                        actions.setFailure(failureOf(error))
                        return null
                    }
                },
            },
        ],
        breakdownSeries: [
            null as TrendBreakdownSeries[] | null,
            {
                loadBreakdown: async (refresh: boolean = false, breakpoint) => {
                    const query = values.breakdownQuery
                    const results = values.results
                    if (!query || !results) {
                        return null
                    }
                    const mode = refresh ? 'force_blocking' : undefined
                    const run = (
                        q: TrendsQuery
                    ): Promise<Map<string, BreakdownCounts> | { failure: OverviewFailure }> => {
                        const controller = new AbortController()
                        const queryId = uuid()
                        let finished = false
                        // A newer load or an unmount stops this query, here and on the server.
                        cache.disposables.add(
                            () => () => {
                                controller.abort()
                                if (!finished) {
                                    void cancelQueryOnServer(values.currentTeamId, queryId)
                                }
                            },
                            'breakdownQuery',
                            { pauseOnPageHidden: false }
                        )
                        return performQuery(q, { signal: controller.signal }, mode, queryId)
                            .finally(() => {
                                finished = true
                            })
                            .then(breakdownCounts, (error) => ({ failure: failureOf(error) }))
                    }
                    let byValue = await run(query)
                    breakpoint()
                    if (!('failure' in byValue)) {
                        // Trends ranks each series on its own, so a value with many runs and a low result can miss
                        // the result series. Then the query runs again on the values the graded series kept.
                        const counts = byValue
                        const graded = [...counts.entries()]
                            .filter(([key, entry]) => key !== BREAKDOWN_OTHER && entry.graded)
                            .map(([key]) => key)
                        if (graded.some((key) => !counts.get(key)?.result)) {
                            byValue = await run(restrictBreakdown(query, graded))
                            breakpoint()
                        }
                    }
                    if ('failure' in byValue) {
                        actions.setBreakdownFailure(byValue.failure)
                        return null
                    }
                    const series = [...byValue.entries()]
                        .filter(([key]) => key !== BREAKDOWN_OTHER)
                        .map(([key, { result = [], graded = [], days }]) => {
                            // An hour repeated when clocks fall back has one key for two buckets, so match them in order.
                            const index = new Map<string, number[]>()
                            days.forEach((day, position) => index.set(day, [...(index.get(day) ?? []), position]))
                            const seen = new Map<string, number>()
                            const at = results.buckets.map((bucket) => {
                                const day = trendsBucketKey(bucket, results.interval)
                                const occurrence = seen.get(day) ?? 0
                                seen.set(day, occurrence + 1)
                                return index.get(day)?.[occurrence]
                            })
                            const gradedCounts = at.map((position) =>
                                position === undefined ? 0 : (graded[position] ?? 0)
                            )
                            return {
                                key,
                                label: key === BREAKDOWN_NULL ? 'Not set' : key,
                                // Trends fills a bucket without runs with 0, which is no result at all.
                                values: at.map((position, bucketIndex) =>
                                    position === undefined || gradedCounts[bucketIndex] === 0
                                        ? NaN
                                        : (result[position] ?? NaN)
                                ),
                                graded: gradedCounts,
                            }
                        })
                    return topBreakdownSeries(series, BREAKDOWN_LIMIT)
                },
            },
        ],
        details: [
            null as DetailsLoad | null,
            {
                loadDetails: async (refresh: boolean = false, breakpoint) => {
                    const row = values.results?.row
                    if (!values.currentTeamId || !row || row.gradedCount === 0) {
                        return null
                    }
                    const { date_from, date_to } = values.request.params
                    // The runs table lists failing runs, so this page leaves the failing examples out.
                    const load = await fetchEvaluationDetails(
                        String(values.currentTeamId),
                        row,
                        { date_from, date_to, ...(refresh ? { refresh: true } : {}) },
                        { recentFailures: false }
                    )
                    breakpoint()
                    return load
                },
            },
        ],
    })),
    reducers({
        // The instant a rolling range ends at, read when results load, so the request selector reads no clock.
        periodNow: [
            Date.now(),
            {
                loadResults: () => Date.now(),
            },
        ],
        // Lines of the old range would be drawn on the new range's buckets until the breakdown reloads.
        breakdownSeries: {
            loadResults: () => null,
        },
        breakdownProperty: [
            null as string | null,
            {
                setBreakdownProperty: (_, { property }) => property,
            },
        ],
        breakdownFailure: [
            null as OverviewFailure | null,
            {
                setBreakdownFailure: (_, { failure }) => failure,
                loadBreakdown: () => null,
            },
        ],
        failure: [
            null as OverviewFailure | null,
            {
                setFailure: (_, { failure }) => failure,
                loadResults: () => null,
            },
        ],
    }),
    selectors({
        // The headline result split by one property, per bucket, next to each value's graded count.
        breakdownQuery: [
            (s) => [s.trendsQuery, s.originalEvaluation, s.breakdownProperty, s.request, s.results],
            (
                trendsQuery: TrendsQuery | null,
                evaluation: EvaluationConfig | null,
                breakdownProperty: string | null,
                request: OverviewRequest,
                results: EvaluationDetailResults | null
            ): TrendsQuery | null => {
                if (!trendsQuery || !evaluation || !breakdownProperty || !request.ready || !results) {
                    return null
                }
                const [headline] = trendsQuery.series
                const { date_from = null, date_to = null } = request.params
                return {
                    ...trendsQuery,
                    kind: NodeKind.TrendsQuery,
                    series: [
                        headline,
                        {
                            ...headline,
                            custom_name: 'Graded',
                            math: HogQLMathType.HogQL,
                            math_hogql: `countIf(${evaluationGradedHogQL(evaluation.output_type)})`,
                        },
                    ],
                    breakdownFilter: {
                        breakdowns: [{ property: breakdownProperty, type: 'event' }],
                        breakdown_limit: BREAKDOWN_QUERY_LIMIT,
                    },
                    // Trends reads a date-only end as that day's midnight when it buckets by hour.
                    dateRange: {
                        date_from,
                        date_to:
                            results.interval === 'hour' && date_to && /^\d{4}-\d{2}-\d{2}$/.test(date_to)
                                ? `${date_to}T23:59:59`
                                : date_to,
                        // A rolling range of hours starts mid-hour, and the overview counts runs from that instant.
                        ...(date_from && date_from.includes('T') ? { explicitDate: true } : {}),
                    },
                    interval: results.interval,
                }
            },
        ],
        request: [
            (s) => [s.runsDateRange, s.timezone, s.weekStartDay, s.periodNow, (_, props) => props.evaluationId],
            (
                runsDateRange: DateRange,
                timezone: string,
                weekStartDay: number,
                periodNow: number,
                evaluationId: string
            ): OverviewRequest => {
                const period = overviewPeriod(
                    { dateFrom: runsDateRange.date_from ?? null, dateTo: runsDateRange.date_to ?? null },
                    timezone,
                    dayjs(periodNow),
                    weekStartDay
                )
                if (!period || period.days > OVERVIEW_MAX_DAYS) {
                    return {
                        params: {
                            date_from: period?.dateFrom,
                            date_to: period?.dateTo,
                            evaluation_ids: [evaluationId],
                        },
                        ready: false,
                        notice: `Pick a range of ${OVERVIEW_MAX_DAYS} days or less to see results over time.`,
                    }
                }
                // The runs table starts a rolling range at midnight N units ago, a day before the overview does.
                const dateFrom =
                    ROLLING_DAYS.test(runsDateRange.date_from ?? '') && !runsDateRange.date_to
                        ? dayjs.utc(period.dateFrom).subtract(1, 'day').format('YYYY-MM-DD')
                        : period.dateFrom
                const params: EvaluationsOverviewRetrieveParams = {
                    date_from: dateFrom,
                    date_to: period.dateTo,
                    evaluation_ids: [evaluationId],
                }
                return { params, ready: true, notice: null }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setBreakdownProperty: ({ property }) => {
            posthog.capture('llma evaluation detail breakdown changed', { property })
            actions.loadBreakdown()
        },
        setRunsDates: () => actions.loadResults(),
        refreshEvaluationRuns: () => actions.loadResults(true),
        loadResultsSuccess: ({ results }) => {
            const refresh = results?.skippedCache ?? false
            actions.loadDetails(refresh)
            actions.loadBreakdown(refresh)
        },
        runOnPastData: () => {
            posthog.capture('llma evaluation detail backfill hint clicked')
            actions.setActiveTab('backfills')
        },
        selectBucket: ({ bucket }) => {
            posthog.capture('llma evaluation detail bucket selected', { interval: values.results?.interval })
            const { dateFrom, dateTo } = bucketDateRange(bucket, values.results?.interval ?? 'day')
            actions.setRunsDates(dateFrom, dateTo)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadResults()
    }),
])
