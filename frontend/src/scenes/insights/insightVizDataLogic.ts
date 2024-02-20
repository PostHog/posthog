import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { DISPLAY_TYPES_WITHOUT_LEGEND } from 'lib/components/InsightLegend/utils'
import { Intervals, intervals } from 'lib/components/IntervalFilter/intervals'
import { parseProperties } from 'lib/components/PropertyFilters/utils'
import {
    NON_TIME_SERIES_DISPLAY_TYPES,
    NON_VALUES_ON_SERIES_DISPLAY_TYPES,
    PERCENT_STACK_VIEW_DISPLAY_TYPE,
} from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { dateMapping } from 'lib/utils'
import posthog from 'posthog-js'
import { insightDataLogic, queryFromKind } from 'scenes/insights/insightDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { sceneLogic } from 'scenes/sceneLogic'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { BASE_MATH_DEFINITIONS } from 'scenes/trends/mathsLogic'

import { queryNodeToFilter, seriesNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import {
    getBreakdown,
    getCompare,
    getDisplay,
    getFormula,
    getInterval,
    getSeries,
    getShowLabelsOnSeries,
    getShowLegend,
    getShowPercentStackView,
    getShowValueOnSeries,
} from '~/queries/nodes/InsightViz/utils'
import {
    BreakdownFilter,
    DateRange,
    FunnelExclusionSteps,
    FunnelsQuery,
    InsightFilter,
    InsightQueryNode,
    Node,
    NodeKind,
    TrendsFilter,
    TrendsQuery,
} from '~/queries/schema'
import {
    filterForQuery,
    filterKeyForQuery,
    isFunnelsQuery,
    isInsightQueryNode,
    isInsightVizNode,
    isLifecycleQuery,
    isNodeWithSource,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
    nodeKindToFilterProperty,
} from '~/queries/utils'
import { BaseMathType, ChartDisplayType, FilterType, InsightLogicProps, IntervalType } from '~/types'

import { insightLogic } from './insightLogic'
import type { insightVizDataLogicType } from './insightVizDataLogicType'

const SHOW_TIMEOUT_MESSAGE_AFTER = 5000

export type QuerySourceUpdate = Omit<Partial<InsightQueryNode>, 'kind'>

export const insightVizDataLogic = kea<insightVizDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightVizDataLogic', key]),

    connect(() => ({
        values: [
            insightDataLogic,
            ['query', 'insightQuery', 'insightData', 'insightDataLoading', 'insightDataError'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
        ],
        actions: [
            insightLogic,
            ['setFilters'],
            insightDataLogic,
            ['setQuery', 'setInsightData', 'loadData', 'loadDataSuccess', 'loadDataFailure'],
        ],
    })),

    actions({
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        updateQuerySource: (querySource: QuerySourceUpdate) => ({ querySource }),
        updateInsightFilter: (insightFilter: InsightFilter) => ({ insightFilter }),
        updateDateRange: (dateRange: DateRange) => ({ dateRange }),
        updateBreakdownFilter: (breakdownFilter: BreakdownFilter) => ({ breakdownFilter }),
        updateDisplay: (display: ChartDisplayType | undefined) => ({ display }),
        setTimedOutQueryId: (id: string | null) => ({ id }),
    }),

    reducers({
        timedOutQueryId: [
            null as null | string,
            {
                setTimedOutQueryId: (_, { id }) => id,
            },
        ],
    }),

    selectors({
        querySource: [
            (s) => [s.query],
            (query) => (isNodeWithSource(query) && isInsightQueryNode(query.source) ? query.source : null),
        ],
        localQuerySource: [
            (s) => [s.querySource, s.filterTestAccountsDefault],
            (querySource, filterTestAccountsDefault) =>
                querySource ? querySource : queryFromKind(NodeKind.TrendsQuery, filterTestAccountsDefault).source,
        ],

        isTrends: [(s) => [s.querySource], (q) => isTrendsQuery(q)],
        isFunnels: [(s) => [s.querySource], (q) => isFunnelsQuery(q)],
        isRetention: [(s) => [s.querySource], (q) => isRetentionQuery(q)],
        isPaths: [(s) => [s.querySource], (q) => isPathsQuery(q)],
        isStickiness: [(s) => [s.querySource], (q) => isStickinessQuery(q)],
        isLifecycle: [(s) => [s.querySource], (q) => isLifecycleQuery(q)],
        isTrendsLike: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isLifecycleQuery(q) || isStickinessQuery(q)],
        supportsDisplay: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isStickinessQuery(q)],
        supportsCompare: [
            (s) => [s.querySource, s.display, s.dateRange],
            (q, display, dateRange) =>
                (isTrendsQuery(q) || isStickinessQuery(q)) &&
                display !== ChartDisplayType.WorldMap &&
                dateRange?.date_from !== 'all',
        ],
        supportsPercentStackView: [
            (s) => [s.querySource, s.display],
            (q, display) =>
                isTrendsQuery(q) &&
                PERCENT_STACK_VIEW_DISPLAY_TYPE.includes(display || ChartDisplayType.ActionsLineGraph),
        ],
        supportsValueOnSeries: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.display],
            (isTrends, isStickiness, isLifecycle, display) => {
                if (isTrends || isStickiness) {
                    return !NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)
                } else if (isLifecycle) {
                    return true
                } else {
                    return false
                }
            },
        ],

        dateRange: [(s) => [s.querySource], (q) => (q ? q.dateRange : null)],
        breakdownFilter: [(s) => [s.querySource], (q) => (q ? getBreakdown(q) : null)],
        display: [(s) => [s.querySource], (q) => (q ? getDisplay(q) : null)],
        compare: [(s) => [s.querySource], (q) => (q ? getCompare(q) : null)],
        formula: [(s) => [s.querySource], (q) => (q ? getFormula(q) : null)],
        series: [(s) => [s.querySource], (q) => (q ? getSeries(q) : null)],
        interval: [(s) => [s.querySource], (q) => (q ? getInterval(q) : null)],
        properties: [(s) => [s.querySource], (q) => (q ? q.properties : null)],
        samplingFactor: [(s) => [s.querySource], (q) => (q ? q.samplingFactor : null)],
        showLegend: [(s) => [s.querySource], (q) => (q ? getShowLegend(q) : null)],
        showValueOnSeries: [(s) => [s.querySource], (q) => (q ? getShowValueOnSeries(q) : null)],
        showLabelOnSeries: [(s) => [s.querySource], (q) => (q ? getShowLabelsOnSeries(q) : null)],
        showPercentStackView: [(s) => [s.querySource], (q) => (q ? getShowPercentStackView(q) : null)],
        vizSpecificOptions: [(s) => [s.query], (q: Node) => (isInsightVizNode(q) ? q.vizSpecificOptions : null)],
        insightFilter: [(s) => [s.querySource], (q) => (q ? filterForQuery(q) : null)],
        trendsFilter: [(s) => [s.querySource], (q) => (isTrendsQuery(q) ? q.trendsFilter : null)],
        funnelsFilter: [(s) => [s.querySource], (q) => (isFunnelsQuery(q) ? q.funnelsFilter : null)],
        retentionFilter: [(s) => [s.querySource], (q) => (isRetentionQuery(q) ? q.retentionFilter : null)],
        pathsFilter: [(s) => [s.querySource], (q) => (isPathsQuery(q) ? q.pathsFilter : null)],
        stickinessFilter: [(s) => [s.querySource], (q) => (isStickinessQuery(q) ? q.stickinessFilter : null)],
        lifecycleFilter: [(s) => [s.querySource], (q) => (isLifecycleQuery(q) ? q.lifecycleFilter : null)],

        isUsingSessionAnalysis: [
            (s) => [s.series, s.breakdownFilter, s.properties],
            (series, breakdownFilter, properties) => {
                const using_session_breakdown = breakdownFilter?.breakdown_type === 'session'
                const using_session_math = series?.some((entity) => entity.math === 'unique_session')
                const using_session_property_math = series?.some((entity) => {
                    // Should be made more generic is we ever add more session properties
                    return entity.math_property === '$session_duration'
                })
                const using_entity_session_property_filter = series?.some((entity) => {
                    return parseProperties(entity.properties).some((property) => property.type === 'session')
                })
                const using_global_session_property_filter = parseProperties(properties).some(
                    (property) => property.type === 'session'
                )
                return (
                    using_session_breakdown ||
                    using_session_math ||
                    using_session_property_math ||
                    using_entity_session_property_filter ||
                    using_global_session_property_filter
                )
            },
        ],
        shouldShowSessionAnalysisWarning: [
            (s) => [s.isUsingSessionAnalysis, s.query],
            (isUsingSessionAnalysis, query) =>
                isUsingSessionAnalysis && !(isInsightVizNode(query) && query.suppressSessionAnalysisWarning),
        ],
        isNonTimeSeriesDisplay: [
            (s) => [s.display],
            (display) => !!display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display),
        ],

        isSingleSeries: [
            (s) => [s.isTrends, s.formula, s.series, s.breakdownFilter],
            (isTrends, formula, series, breakdownFilter): boolean => {
                return ((isTrends && !!formula) || (series || []).length <= 1) && !breakdownFilter?.breakdown
            },
        ],

        valueOnSeries: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.insightFilter],
            (isTrends, isStickiness, isLifecycle, insightFilter): boolean => {
                return !!(
                    ((isTrends || isStickiness || isLifecycle) &&
                        (insightFilter as TrendsFilter)?.showValuesOnSeries) ||
                    // pie charts have value checked by default
                    (isTrends &&
                        (insightFilter as TrendsFilter)?.display === ChartDisplayType.ActionsPie &&
                        (insightFilter as TrendsFilter)?.showValuesOnSeries === undefined)
                )
            },
        ],

        hasLegend: [
            (s) => [s.isTrends, s.isStickiness, s.display],
            (isTrends, isStickiness, display) =>
                (isTrends || isStickiness) &&
                !DISPLAY_TYPES_WITHOUT_LEGEND.includes(display || ChartDisplayType.ActionsLineGraph),
        ],

        hasFormula: [(s) => [s.formula], (formula) => formula !== undefined],

        activeUsersMath: [
            (s) => [s.series],
            (series): BaseMathType.MonthlyActiveUsers | BaseMathType.WeeklyActiveUsers | null =>
                getActiveUsersMath(series),
        ],
        enabledIntervals: [
            (s) => [s.activeUsersMath],
            (activeUsersMath) => {
                const enabledIntervals: Intervals = { ...intervals }

                if (activeUsersMath) {
                    // Disallow grouping by hour for WAUs/MAUs as it's an expensive query that produces a view that's not useful for users
                    enabledIntervals.hour = {
                        ...enabledIntervals.hour,
                        disabledReason:
                            'Grouping by hour is not supported on insights with weekly or monthly active users series.',
                    }

                    // Disallow grouping by month for WAUs as the resulting view is misleading to users
                    if (activeUsersMath === BaseMathType.WeeklyActiveUsers) {
                        enabledIntervals.month = {
                            ...enabledIntervals.month,
                            disabledReason:
                                'Grouping by month is not supported on insights with weekly active users series.',
                        }
                    }
                }

                return enabledIntervals
            },
        ],

        erroredQueryId: [
            (s) => [s.insightDataError],
            (insightDataError) => {
                return insightDataError?.queryId || null
            },
        ],
        validationError: [
            (s) => [s.insightDataError],
            (insightDataError): string | null => {
                // We use 512 for query timeouts
                return insightDataError?.status === 400 || insightDataError?.status === 512
                    ? insightDataError.detail?.replace('Try ', 'Try ') // Add unbreakable space for better line breaking
                    : null
            },
        ],

        timezone: [(s) => [s.insightData], (insightData) => insightData?.timezone || 'UTC'],

        /*
         * Funnels
         */
        isFunnelWithEnoughSteps: [
            (s) => [s.series],
            (series) => {
                return (series?.length || 0) > 1
            },
        ],

        // Exclusion filters
        exclusionDefaultStepRange: [
            (s) => [s.querySource],
            (querySource: FunnelsQuery): FunnelExclusionSteps => ({
                funnelFromStep: 0,
                funnelToStep: (querySource.series || []).length > 1 ? querySource.series.length - 1 : 1,
            }),
        ],
        exclusionFilters: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): FilterType => ({
                events: funnelsFilter?.exclusions?.map(({ funnelFromStep, funnelToStep, ...rest }, index) => ({
                    funnel_from_step: funnelFromStep,
                    funnel_to_step: funnelToStep,
                    order: index,
                    ...seriesNodeToFilter(rest),
                })),
            }),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        updateDateRange: ({ dateRange }) => {
            actions.updateQuerySource({ dateRange: { ...values.dateRange, ...dateRange } })
        },
        updateBreakdownFilter: ({ breakdownFilter }) => {
            actions.updateQuerySource({
                breakdownFilter: { ...values.breakdownFilter, ...breakdownFilter },
            } as Partial<TrendsQuery>)
        },
        updateInsightFilter: ({ insightFilter }) => {
            const filterProperty = filterKeyForQuery(values.localQuerySource)
            actions.updateQuerySource({
                [filterProperty]: { ...values.localQuerySource[filterProperty], ...insightFilter },
            })
        },
        updateDisplay: ({ display }) => {
            actions.updateInsightFilter({ display })
        },
        updateQuerySource: ({ querySource }) => {
            actions.setQuery({
                ...values.query,
                source: {
                    ...values.querySource,
                    ...handleQuerySourceUpdateSideEffects(querySource, values.querySource as InsightQueryNode),
                },
            } as Node)
        },
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                if (props.setQuery) {
                    props.setQuery(query)
                }

                const querySource = query.source
                const filters = queryNodeToFilter(querySource)
                actions.setFilters(filters)
            }
        },
        loadData: async ({ queryId }, breakpoint) => {
            actions.setTimedOutQueryId(null)

            await breakpoint(SHOW_TIMEOUT_MESSAGE_AFTER) // By timeout we just mean long loading time here

            if (values.insightDataLoading) {
                actions.setTimedOutQueryId(queryId)
                const tags = {
                    kind: values.querySource?.kind,
                    scene: sceneLogic.isMounted() ? sceneLogic.values.scene : null,
                }
                posthog.capture('insight timeout message shown', tags)
            }
        },
        loadDataSuccess: () => {
            actions.setTimedOutQueryId(null)
        },
        loadDataFailure: () => {
            actions.setTimedOutQueryId(null)
        },
    })),
])

const getActiveUsersMath = (
    series: TrendsQuery['series'] | null | undefined
): BaseMathType.WeeklyActiveUsers | BaseMathType.MonthlyActiveUsers | null => {
    for (const seriesItem of series || []) {
        if (seriesItem.math === BaseMathType.WeeklyActiveUsers) {
            return BaseMathType.WeeklyActiveUsers
        }

        if (seriesItem.math === BaseMathType.MonthlyActiveUsers) {
            return BaseMathType.MonthlyActiveUsers
        }
    }

    return null
}

const handleQuerySourceUpdateSideEffects = (
    update: QuerySourceUpdate,
    currentState: InsightQueryNode
): QuerySourceUpdate => {
    const mergedUpdate = { ...update } as InsightQueryNode

    const maybeChangedSeries = (update as TrendsQuery).series || null
    const maybeChangedActiveUsersMath = maybeChangedSeries ? getActiveUsersMath(maybeChangedSeries) : null
    const kind = (update as Partial<InsightQueryNode>).kind || currentState.kind
    const insightFilter = currentState[nodeKindToFilterProperty[currentState.kind]] as Partial<InsightFilter>
    const maybeChangedInsightFilter = update[nodeKindToFilterProperty[kind]] as Partial<InsightFilter>

    const interval = (currentState as TrendsQuery).interval

    /*
     * Series change side effects.
     */

    // If the user just flipped an event action to use WAUs/MAUs math and their
    // current interval is unsupported by the math type, switch their interval
    // to an appropriate allowed interval and inform them of the change via a toast
    if (maybeChangedActiveUsersMath !== null && (interval === 'hour' || interval === 'month')) {
        if (interval === 'hour') {
            lemonToast.info(
                `Switched to grouping by day, because "${BASE_MATH_DEFINITIONS[maybeChangedActiveUsersMath].name}" does not support grouping by ${interval}.`
            )
            ;(mergedUpdate as Partial<TrendsQuery>).interval = 'day'
        } else if (interval === 'month' && maybeChangedActiveUsersMath === BaseMathType.WeeklyActiveUsers) {
            lemonToast.info(
                `Switched to grouping by week, because "${BASE_MATH_DEFINITIONS[maybeChangedActiveUsersMath].name}" does not support grouping by ${interval}.`
            )
            ;(mergedUpdate as Partial<TrendsQuery>).interval = 'week'
        }
    }

    /*
     * Date range change side effects.
     */
    if (
        !isRetentionQuery(currentState) &&
        !isPathsQuery(currentState) && // TODO: Apply side logic more elegantly
        update.dateRange &&
        update.dateRange.date_from &&
        (update.dateRange.date_from !== currentState.dateRange?.date_from ||
            update.dateRange.date_to !== currentState.dateRange?.date_to)
    ) {
        const { date_from, date_to } = { ...currentState.dateRange, ...update.dateRange }

        if (date_from && date_to && dayjs(date_from).isValid() && dayjs(date_to).isValid()) {
            if (dayjs(date_to).diff(dayjs(date_from), 'day') <= 3) {
                ;(mergedUpdate as Partial<TrendsQuery>).interval = 'hour'
            } else if (dayjs(date_to).diff(dayjs(date_from), 'month') <= 3) {
                ;(mergedUpdate as Partial<TrendsQuery>).interval = 'day'
            } else {
                ;(mergedUpdate as Partial<TrendsQuery>).interval = 'month'
            }
        } else {
            // get a defaultInterval for dateOptions that have a default value
            let newDefaultInterval: IntervalType = 'day'
            for (const { key, values, defaultInterval } of dateMapping) {
                if (
                    values[0] === date_from &&
                    values[1] === (date_to || undefined) &&
                    key !== 'Custom' &&
                    defaultInterval
                ) {
                    newDefaultInterval = defaultInterval
                    break
                }
            }
            ;(mergedUpdate as Partial<TrendsQuery>).interval = newDefaultInterval
        }
    }

    /*
     * Display change side effects.
     */
    const display = (insightFilter as Partial<TrendsFilter>)?.display || ChartDisplayType.ActionsLineGraph
    const maybeChangedDisplay =
        (maybeChangedInsightFilter as Partial<TrendsFilter>)?.display || ChartDisplayType.ActionsLineGraph

    // For the map, make sure we are breaking down by country
    if (
        kind === NodeKind.TrendsQuery &&
        display !== maybeChangedDisplay &&
        maybeChangedDisplay === ChartDisplayType.WorldMap
    ) {
        const math = (maybeChangedSeries || (currentState as TrendsQuery).series)?.[0].math

        mergedUpdate['breakdownFilter'] = {
            breakdown: '$geoip_country_code',
            breakdown_type: ['dau', 'weekly_active', 'monthly_active'].includes(math || '') ? 'person' : 'event',
        }
    }

    return mergedUpdate
}
