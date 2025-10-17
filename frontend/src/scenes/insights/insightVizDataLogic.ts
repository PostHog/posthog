import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import {
    DISPLAY_TYPES_WITHOUT_DETAILED_RESULTS,
    DISPLAY_TYPES_WITHOUT_LEGEND,
} from 'lib/components/InsightLegend/utils'
import { Intervals, intervals } from 'lib/components/IntervalFilter/intervals'
import { parseProperties } from 'lib/components/PropertyFilters/utils'
import { NON_TIME_SERIES_DISPLAY_TYPES, NON_VALUES_ON_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { dateMapping, is12HoursOrLess, isLessThan2Days } from 'lib/utils'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { getClampedFunnelStepRange } from 'scenes/funnels/funnelUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { AggregationType } from 'scenes/insights/views/InsightsTable/insightsTableDataLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { BASE_MATH_DEFINITIONS } from 'scenes/trends/mathsLogic'

import { actionsModel } from '~/models/actionsModel'
import { seriesNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { extractValidationError, getAllEventNames, queryFromKind } from '~/queries/nodes/InsightViz/utils'
import {
    BreakdownFilter,
    CompareFilter,
    DataWarehouseNode,
    DatabaseSchemaField,
    DateRange,
    FunnelExclusionSteps,
    FunnelsFilter,
    FunnelsQuery,
    InsightFilter,
    InsightQueryNode,
    Node,
    NodeKind,
    TrendsFilter,
    TrendsFormulaNode,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    filterForQuery,
    filterKeyForQuery,
    getBreakdown,
    getCompareFilter,
    getDisplay,
    getFormula,
    getFormulaNodes,
    getFormulas,
    getGoalLines,
    getInterval,
    getResultCustomizationBy,
    getSeries,
    getShowAlertThresholdLines,
    getShowLabelsOnSeries,
    getShowLegend,
    getShowMultipleYAxes,
    getShowPercentStackView,
    getShowValuesOnSeries,
    getYAxisScaleType,
    isActionsNode,
    isDataWarehouseNode,
    isEventsNode,
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
    supportsPercentStackView,
} from '~/queries/utils'
import { BaseMathType, ChartDisplayType, FilterType, InsightLogicProps, SlowQueryPossibilities } from '~/types'

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
            databaseTableListLogic,
            ['dataWarehouseTablesMap'],
            dataThemeLogic,
            ['getTheme'],
        ],
        actions: [insightDataLogic, ['setQuery', 'setInsightData', 'loadData', 'loadDataSuccess', 'loadDataFailure']],
    })),

    actions({
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        updateQuerySource: (querySource: QuerySourceUpdate) => ({ querySource }),
        updateInsightFilter: (insightFilter: InsightFilter) => ({ insightFilter }),
        updateDateRange: (dateRange: DateRange) => ({ dateRange }),
        updateBreakdownFilter: (breakdownFilter: BreakdownFilter) => ({ breakdownFilter }),
        updateCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        updateDisplay: (display: ChartDisplayType | undefined) => ({ display }),
        setTimedOutQueryId: (id: string | null) => ({ id }),
        setIsIntervalManuallySet: (isIntervalManuallySet: boolean) => ({ isIntervalManuallySet }),
        toggleFormulaMode: true,
        setDetailedResultsAggregationType: (detailedResultsAggregationType: AggregationType) => ({
            detailedResultsAggregationType,
        }),
    }),

    reducers({
        timedOutQueryId: [
            null as null | string,
            {
                setTimedOutQueryId: (_, { id }) => id,
            },
        ],

        isIntervalManuallySet: [
            false,
            {
                updateQuerySource: (state, { querySource }) => {
                    return 'interval' in querySource ? true : state
                },
                setIsIntervalManuallySet: (_, { isIntervalManuallySet }) => isIntervalManuallySet,
            },
        ],
        isFormulaModeOpenedExplicitly: [
            false,
            {
                toggleFormulaMode: (state) => !state,
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
        isTrendsLike: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isLifecycleQuery(q) || isStickinessQuery(q)], // this is for filtering out world map
        supportsDisplay: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isStickinessQuery(q)],
        supportsCompare: [
            (s) => [s.querySource, s.display, s.dateRange],
            (q, display, dateRange) =>
                (isTrendsQuery(q) || isStickinessQuery(q)) &&
                display !== ChartDisplayType.WorldMap &&
                display !== ChartDisplayType.CalendarHeatmap &&
                dateRange?.date_from !== 'all',
        ],
        supportsPercentStackView: [(s) => [s.querySource], (q) => supportsPercentStackView(q)],
        supportsValueOnSeries: [
            (s) => [s.isTrends, s.isFunnels, s.isStickiness, s.isLifecycle, s.display],
            (isTrends, isFunnels, isStickiness, isLifecycle, display) => {
                if (isTrends || isStickiness) {
                    return !NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)
                } else if (isLifecycle || isFunnels) {
                    return true
                }
                return false
            },
        ],
        supportsResultCustomizationBy: [
            (s) => [s.isTrends, s.display],
            (isTrends, display) =>
                isTrends && [ChartDisplayType.ActionsLineGraph].includes(display || ChartDisplayType.ActionsLineGraph),
        ],

        dateRange: [(s) => [s.querySource], (q) => (q ? q.dateRange : null)],
        breakdownFilter: [(s) => [s.querySource], (q) => (q ? getBreakdown(q) : null)],
        compareFilter: [(s) => [s.querySource], (q) => (q ? getCompareFilter(q) : null)],
        display: [(s) => [s.querySource], (q) => (q ? getDisplay(q) : null)],
        formula: [
            (s) => [s.querySource],
            (querySource: InsightQueryNode | null) => (querySource ? getFormula(querySource) : null),
        ],
        formulas: [
            (s) => [s.querySource],
            (querySource: InsightQueryNode | null) => (querySource ? getFormulas(querySource) : null),
        ],
        formulaNodes: [
            (s) => [s.querySource],
            (querySource: InsightQueryNode | null): TrendsFormulaNode[] => {
                const formula = getFormula(querySource)
                const formulas = getFormulas(querySource)

                return querySource
                    ? getFormulaNodes(querySource) ||
                          (formulas ? formulas.map((f) => ({ formula: f })) : formula ? [{ formula }] : [])
                    : []
            },
        ],
        series: [(s) => [s.querySource], (q) => (q ? getSeries(q) : null)],
        interval: [(s) => [s.querySource], (q) => (q ? getInterval(q) : null)],
        properties: [(s) => [s.querySource], (q) => (q ? q.properties : null)],
        samplingFactor: [(s) => [s.querySource], (q) => (q ? q.samplingFactor : null)],
        showAlertThresholdLines: [(s) => [s.querySource], (q) => (q ? getShowAlertThresholdLines(q) : null)],
        showLegend: [(s) => [s.querySource], (q) => (q ? getShowLegend(q) : null)],
        showValuesOnSeries: [(s) => [s.querySource], (q) => (q ? getShowValuesOnSeries(q) : null)],
        showLabelOnSeries: [(s) => [s.querySource], (q) => (q ? getShowLabelsOnSeries(q) : null)],
        showPercentStackView: [(s) => [s.querySource], (q) => (q ? getShowPercentStackView(q) : null)],
        yAxisScaleType: [(s) => [s.querySource], (q) => (q ? getYAxisScaleType(q) : null)],
        showMultipleYAxes: [(s) => [s.querySource], (q) => (q ? getShowMultipleYAxes(q) : null)],
        resultCustomizationBy: [(s) => [s.querySource], (q) => (q ? getResultCustomizationBy(q) : null)],
        goalLines: [(s) => [s.querySource], (q) => (isTrendsQuery(q) || isFunnelsQuery(q) ? getGoalLines(q) : null)],
        insightFilter: [(s) => [s.querySource], (q) => (q ? filterForQuery(q) : null)],
        trendsFilter: [(s) => [s.querySource], (q) => (isTrendsQuery(q) ? q.trendsFilter : null)],
        detailedResultsAggregationType: [
            (s) => [s.querySource],
            (querySource): AggregationType | undefined => {
                if (isTrendsQuery(querySource)) {
                    return querySource.trendsFilter?.detailedResultsAggregationType as AggregationType | undefined
                }
            },
        ],
        funnelsFilter: [(s) => [s.querySource], (q) => (isFunnelsQuery(q) ? q.funnelsFilter : null)],
        retentionFilter: [(s) => [s.querySource], (q) => (isRetentionQuery(q) ? q.retentionFilter : null)],
        pathsFilter: [(s) => [s.querySource], (q) => (isPathsQuery(q) ? q.pathsFilter : null)],
        stickinessFilter: [(s) => [s.querySource], (q) => (isStickinessQuery(q) ? q.stickinessFilter : null)],
        lifecycleFilter: [(s) => [s.querySource], (q) => (isLifecycleQuery(q) ? q.lifecycleFilter : null)],
        funnelPathsFilter: [(s) => [s.querySource], (q) => (isPathsQuery(q) ? q.funnelPathsFilter : null)],
        vizSpecificOptions: [(s) => [s.query], (q: Node) => (isInsightVizNode(q) ? q.vizSpecificOptions : null)],

        isUsingSessionAnalysis: [
            (s) => [s.series, s.breakdownFilter, s.properties],
            (series, breakdownFilter, properties) => {
                const using_session_breakdown =
                    breakdownFilter?.breakdown_type === 'session' ||
                    breakdownFilter?.breakdowns?.find((breakdown) => breakdown.type === 'session')
                const using_session_math = series?.some((entity) => entity.math === 'unique_session')
                const using_session_property_math = series?.some((entity) => {
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
            (s) => [s.isTrends, s.formula, s.formulas, s.formulaNodes, s.series, s.breakdownFilter],
            (
                isTrends: boolean,
                formula: string | undefined,
                formulas: string[] | undefined,
                formulaNodes: TrendsFormulaNode[] | undefined,
                series: any[],
                breakdownFilter: BreakdownFilter | null
            ): boolean => {
                const hasSingleFormula =
                    (formula && !formulas) ||
                    (formulas && formulas.length === 1) ||
                    (formulaNodes && formulaNodes.length === 1)
                return (isTrends && hasSingleFormula) || ((series || []).length <= 1 && !breakdownFilter?.breakdown)
            },
        ],
        isBreakdownSeries: [
            (s) => [s.breakdownFilter],
            (breakdownFilter): boolean => {
                return !!breakdownFilter?.breakdown
            },
        ],

        hasDataWarehouseSeries: [
            (s) => [s.isTrends, s.series],
            (isTrends, series): boolean => {
                return isTrends && (series || []).length > 0 && !!series?.some((node) => isDataWarehouseNode(node))
            },
        ],

        currentDataWarehouseSchemaColumns: [
            (s) => [
                s.series,
                s.isSingleSeries,
                s.hasDataWarehouseSeries,
                s.isBreakdownSeries,
                s.dataWarehouseTablesMap,
            ],
            (
                series,
                isSingleSeries,
                hasDataWarehouseSeries,
                isBreakdownSeries,
                dataWarehouseTablesMap
            ): DatabaseSchemaField[] => {
                if (
                    !series ||
                    series.length === 0 ||
                    (!isSingleSeries && !isBreakdownSeries) ||
                    !hasDataWarehouseSeries
                ) {
                    return []
                }

                return Object.values(dataWarehouseTablesMap[(series[0] as DataWarehouseNode)?.table_name]?.fields ?? {})
            },
        ],

        valueOnSeries: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.insightFilter],
            (isTrends, isStickiness, isLifecycle, insightFilter): boolean => {
                return !!(
                    ((isTrends || isStickiness || isLifecycle) &&
                        (insightFilter as TrendsFilter)?.showValuesOnSeries) ||
                    (isTrends &&
                        (insightFilter as TrendsFilter)?.display === ChartDisplayType.ActionsPie &&
                        (insightFilter as TrendsFilter)?.showValuesOnSeries === undefined)
                )
            },
        ],

        hasLegend: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.display],
            (isTrends, isStickiness, isLifecycle, display) =>
                (isTrends || isStickiness || isLifecycle) &&
                !(display && DISPLAY_TYPES_WITHOUT_LEGEND.includes(display)),
        ],

        hasDetailedResultsTable: [
            (s) => [s.isTrends, s.isStickiness, s.display],
            (isTrends: boolean, isStickiness: boolean, display: ChartDisplayType | undefined) =>
                (isTrends || isStickiness) && !(display && DISPLAY_TYPES_WITHOUT_DETAILED_RESULTS.includes(display)),
        ],

        hasFormula: [
            (s) => [s.formulaNodes, s.isFormulaModeOpenedExplicitly],
            (formulaNodes: TrendsFormulaNode[], isFormulaModeOpenedExplicitly: boolean): boolean => {
                if (isFormulaModeOpenedExplicitly) {
                    return true
                }
                return formulaNodes.length > 0
            },
        ],

        activeUsersMath: [
            (s) => [s.series],
            (series): BaseMathType.MonthlyActiveUsers | BaseMathType.WeeklyActiveUsers | null =>
                getActiveUsersMath(series),
        ],
        enabledIntervals: [
            (s) => [s.activeUsersMath, s.isTrends],
            (activeUsersMath, isTrends): Intervals => {
                const enabledIntervals: Intervals = { ...intervals }

                if (activeUsersMath) {
                    enabledIntervals.hour = {
                        ...enabledIntervals.hour,
                        disabledReason:
                            'Grouping by hour is not supported on insights with weekly or monthly active users series.',
                    }

                    if (activeUsersMath === BaseMathType.WeeklyActiveUsers) {
                        enabledIntervals.month = {
                            ...enabledIntervals.month,
                            disabledReason:
                                'Grouping by month is not supported on insights with weekly active users series.',
                        }
                    }
                }

                if (!isTrends) {
                    enabledIntervals.minute = {
                        ...enabledIntervals.minute,
                        hidden: true,
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
            (insightDataError): string | null => extractValidationError(insightDataError),
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

        // all events used in the insight (useful for fetching only relevant property definitions)
        allEventNames: [
            (s) => [s.querySource, actionsModel.selectors.actions],
            (querySource, actions) => (querySource ? getAllEventNames(querySource, actions) : []),
        ],

        theme: [(s) => [s.getTheme, s.querySource], (getTheme, querySource) => getTheme(querySource?.dataColorTheme)],

        isAllEventsQuery: [
            (s) => [s.querySource],
            (querySource) => {
                return (
                    (querySource?.kind === NodeKind.TrendsQuery || querySource?.kind === NodeKind.FunnelsQuery) &&
                    querySource?.series?.some((s) => s.name === 'All events')
                )
            },
        ],
        isFirstTimeForUserQuery: [
            (s) => [s.querySource],
            (querySource) => {
                return (
                    querySource?.kind === NodeKind.TrendsQuery &&
                    querySource?.series?.some((s) =>
                        ['first_matching_event_for_user', 'first_time_for_user'].includes(s.math || '')
                    )
                )
            },
        ],
        isStrictFunnelQuery: [
            (s) => [s.querySource],
            (querySource) => {
                return (
                    querySource?.kind === NodeKind.FunnelsQuery &&
                    querySource?.funnelsFilter?.funnelOrderType === 'strict'
                )
            },
        ],
        slowQueryPossibilities: [
            (s) => [s.isAllEventsQuery, s.isFirstTimeForUserQuery, s.isStrictFunnelQuery],
            (isAllEventsQuery, isFirstTimeForUserQuery, isStrictFunnelQuery): SlowQueryPossibilities[] => {
                const possibilities: SlowQueryPossibilities[] = []
                if (isAllEventsQuery) {
                    possibilities.push('all_events')
                }
                if (isFirstTimeForUserQuery) {
                    possibilities.push('first_time_for_user')
                }
                if (isStrictFunnelQuery) {
                    possibilities.push('strict_funnel')
                }
                return possibilities
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        // query
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                if (query.source.kind === NodeKind.TrendsQuery) {
                    // Disable filter test account when using a data warehouse series
                    const hasWarehouseSeries = query.source.series?.some((node) => isDataWarehouseNode(node))
                    const filterTestAccountsEnabled = query.source.filterTestAccounts ?? false
                    if (hasWarehouseSeries && filterTestAccountsEnabled) {
                        query.source.filterTestAccounts = false
                    }
                }

                if (props.setQuery) {
                    props.setQuery(query)
                }
            }
        },

        // query source
        updateQuerySource: ({ querySource }) => {
            actions.setQuery({
                ...values.query,
                source: {
                    ...values.querySource,
                    ...handleQuerySourceUpdateSideEffects(
                        querySource,
                        values.querySource as InsightQueryNode,
                        values.isIntervalManuallySet
                    ),
                },
            } as Node)
        },

        // query source properties
        updateDateRange: async ({ dateRange }, breakpoint) => {
            await breakpoint(300)
            actions.updateQuerySource({
                dateRange: {
                    ...values.dateRange,
                    ...dateRange,
                },
                ...(dateRange.date_from == 'all' ? ({ compareFilter: undefined } as Partial<TrendsQuery>) : {}),
            })
        },
        updateBreakdownFilter: async ({ breakdownFilter }, breakpoint) => {
            await breakpoint(500) // extra debounce time because of number input
            const update: Partial<TrendsQuery> = { breakdownFilter: { ...values.breakdownFilter, ...breakdownFilter } }
            actions.updateQuerySource(update)
        },
        updateCompareFilter: async ({ compareFilter }, breakpoint) => {
            await breakpoint(500) // extra debounce time because of number input
            const update: Partial<TrendsQuery> = { compareFilter: { ...values.compareFilter, ...compareFilter } }
            actions.updateQuerySource(update)
        },

        // insight filter
        updateInsightFilter: async ({ insightFilter }, breakpoint) => {
            await breakpoint(300)
            const filterProperty = filterKeyForQuery(values.localQuerySource)
            actions.updateQuerySource({
                [filterProperty]: { ...values.localQuerySource[filterProperty], ...insightFilter },
            })
        },

        // insight filter properties
        updateDisplay: ({ display }) => {
            actions.updateInsightFilter({ display })
        },

        setDetailedResultsAggregationType: ({ detailedResultsAggregationType }) => {
            actions.updateInsightFilter({
                detailedResultsAggregationType: detailedResultsAggregationType,
            })
        },

        // data loading side effects i.e. displaying loading screens for queries with longer duration
        loadData: async ({ queryId }, breakpoint) => {
            actions.setTimedOutQueryId(null)

            await breakpoint(SHOW_TIMEOUT_MESSAGE_AFTER) // By timeout we just mean long loading time here

            if (values.insightDataLoading) {
                actions.setTimedOutQueryId(queryId)
                const tags = {
                    kind: values.querySource?.kind,
                    scene: sceneLogic.isMounted() ? sceneLogic.values.activeSceneId : null,
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
        toggleFormulaMode: () => {
            // Only if formula mode is already open should we trigger a query.
            if (values.hasFormula) {
                actions.updateInsightFilter({ formula: undefined, formulas: undefined, formulaNodes: [] })
            }
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
    currentState: InsightQueryNode,
    isIntervalManuallySet: boolean
): QuerySourceUpdate => {
    const mergedUpdate = { ...update } as InsightQueryNode

    const maybeChangedSeries = (update as TrendsQuery).series || null
    const maybeChangedActiveUsersMath = maybeChangedSeries ? getActiveUsersMath(maybeChangedSeries) : null
    const kind = (update as Partial<InsightQueryNode>).kind || currentState.kind
    const insightFilter = currentState[nodeKindToFilterProperty[currentState.kind]] as Partial<InsightFilter>
    const maybeChangedInsightFilter = update[nodeKindToFilterProperty[kind]] as Partial<InsightFilter>

    const interval = (currentState as TrendsQuery).interval

    const oneHourDateRange = {
        date_from: '-1h',
    }

    /*
     * Series change side effects.
     */

    // If the user just flipped an event action to use WAUs/MAUs math and their
    // current interval is unsupported by the math type, switch their interval
    // to an appropriate allowed interval and inform them of the change via a toast
    if (
        maybeChangedActiveUsersMath !== null &&
        (interval === 'hour' || interval === 'month' || interval === 'minute')
    ) {
        if (interval === 'hour' || interval === 'minute') {
            lemonToast.info(
                `Switched to grouping by day, because "${BASE_MATH_DEFINITIONS[maybeChangedActiveUsersMath].name}" does not support grouping by ${interval}.`
            )
            ;(mergedUpdate as TrendsQuery).interval = 'day'
        } else if (interval === 'month' && maybeChangedActiveUsersMath === BaseMathType.WeeklyActiveUsers) {
            lemonToast.info(
                `Switched to grouping by week, because "${BASE_MATH_DEFINITIONS[maybeChangedActiveUsersMath].name}" does not support grouping by ${interval}.`
            )
            ;(mergedUpdate as TrendsQuery).interval = 'week'
        }
    }

    // clamp the funnel steps
    if (
        maybeChangedSeries &&
        isFunnelsQuery(currentState) &&
        ((insightFilter as FunnelsFilter)?.funnelFromStep != null ||
            (insightFilter as FunnelsFilter)?.funnelToStep != null)
    ) {
        ;(mergedUpdate as FunnelsQuery).funnelsFilter = {
            ...(insightFilter as FunnelsFilter),
            ...getClampedFunnelStepRange(insightFilter as FunnelsFilter, maybeChangedSeries),
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
            update.dateRange.date_to !== currentState.dateRange?.date_to) &&
        !isIntervalManuallySet // Only auto-adjust interval if not manually set
    ) {
        const { date_from, date_to } = { ...currentState.dateRange, ...update.dateRange }

        if (date_from && date_to && dayjs(date_from).isValid() && dayjs(date_to).isValid()) {
            if (dayjs(date_to).diff(dayjs(date_from), 'day') <= 3) {
                ;(mergedUpdate as TrendsQuery).interval = 'hour'
            } else if (dayjs(date_to).diff(dayjs(date_from), 'month') <= 3) {
                ;(mergedUpdate as TrendsQuery).interval = 'day'
            } else {
                ;(mergedUpdate as TrendsQuery).interval = 'month'
            }
        } else {
            // get a defaultInterval for dateOptions that have a default value
            const selectedDateMapping = dateMapping.find(
                ({ key, values, defaultInterval }) =>
                    values[0] === date_from &&
                    values[1] === (date_to || undefined) &&
                    key !== 'Custom' &&
                    defaultInterval
            )

            if (!selectedDateMapping && isTrendsQuery(currentState) && is12HoursOrLess(date_from)) {
                ;(mergedUpdate as TrendsQuery).interval = 'minute'
            } else if (!selectedDateMapping && isLessThan2Days(date_from)) {
                ;(mergedUpdate as TrendsQuery).interval = 'hour'
            } else {
                ;(mergedUpdate as TrendsQuery).interval = selectedDateMapping?.defaultInterval || 'day'
            }
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

    // if mixed, clear breakdown and trends filter
    if (
        kind === NodeKind.TrendsQuery &&
        (mergedUpdate as TrendsQuery).series?.length >= 0 &&
        (mergedUpdate as TrendsQuery).series.some((series) => isDataWarehouseNode(series)) &&
        (mergedUpdate as TrendsQuery).series.some((series) => isActionsNode(series) || isEventsNode(series))
    ) {
        mergedUpdate['breakdownFilter'] = null
        mergedUpdate['properties'] = []
    }

    // Remove breakdown filter if display type is BoldNumber because it is not supported
    if (kind === NodeKind.TrendsQuery && maybeChangedDisplay === ChartDisplayType.BoldNumber) {
        mergedUpdate['breakdownFilter'] = null
    }

    // Remove breakdown filter if display type is Heatmap because it is not supported
    if (kind === NodeKind.TrendsQuery && maybeChangedDisplay === ChartDisplayType.CalendarHeatmap) {
        mergedUpdate['breakdownFilter'] = null
    }

    // Don't allow minutes on anything other than Trends
    if (
        currentState.kind == NodeKind.TrendsQuery &&
        kind !== NodeKind.TrendsQuery &&
        (('interval' in mergedUpdate && mergedUpdate?.interval) || interval) == 'minute'
    ) {
        ;(mergedUpdate as TrendsQuery).interval = 'hour'
    }

    // If the user changes the interval to 'minute' and the date_range is more than 12 hours, reset it to 1 hour
    if (kind == NodeKind.TrendsQuery && (mergedUpdate as TrendsQuery)?.interval == 'minute' && interval !== 'minute') {
        const { date_from, date_to } = { ...currentState.dateRange, ...update.dateRange }

        if (
            // When insights are created, they might not have an explicit dateRange set. Change it to an hour if the interval is minute.
            (!date_from && !date_to) ||
            // If the interval is set manually to a range greater than 12 hours, change it to an hour
            (date_from &&
                date_to &&
                dayjs(date_from).isValid() &&
                dayjs(date_to).isValid() &&
                dayjs(date_to).diff(dayjs(date_from), 'hour') > 12)
        ) {
            ;(mergedUpdate as TrendsQuery).dateRange = oneHourDateRange
        } else {
            if (!is12HoursOrLess(date_from)) {
                ;(mergedUpdate as TrendsQuery).dateRange = oneHourDateRange
            }
        }
    }

    // If we've changed interval, clear smoothings
    if (kind == NodeKind.TrendsQuery) {
        if (
            (currentState as Partial<TrendsQuery>)?.trendsFilter?.smoothingIntervals !== undefined &&
            (mergedUpdate as TrendsQuery)?.interval !== undefined &&
            (mergedUpdate as TrendsQuery).interval !== interval
        ) {
            ;(mergedUpdate as TrendsQuery).trendsFilter = {
                ...(currentState as TrendsQuery).trendsFilter,
                smoothingIntervals: undefined,
            }
        }
    }

    return mergedUpdate
}
