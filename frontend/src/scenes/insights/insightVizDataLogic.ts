import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import {
    DISPLAY_TYPES_WITHOUT_DETAILED_RESULTS,
    DISPLAY_TYPES_WITHOUT_LEGEND,
} from 'lib/components/InsightLegend/utils'
import { Intervals, intervals } from 'lib/components/IntervalFilter/intervals'
import { parseProperties } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES, NON_VALUES_ON_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dateMapping, is12HoursOrLess, isLessThan2Days } from 'lib/utils/dateFilters'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
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
import {
    extractValidationError,
    extractValidationErrorCode,
    getAllEventNames,
    queryFromKind,
} from '~/queries/nodes/InsightViz/utils'
import {
    AnyDataWarehouseNode,
    AnyEntityNode,
    BreakdownFilter,
    CompareFilter,
    DatabaseSchemaField,
    DateRange,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
    GroupNode,
    InsightFilter,
    InsightFilterProperty,
    InsightQueryNode,
    LifecycleQuery,
    Node,
    NodeKind,
    ProductAnalyticsInsightQueryNode,
    RetentionQuery,
    StickinessQuery,
    TrendsFilter,
    TrendsFormulaNode,
    TrendsQuery,
    VizSpecificOptions,
} from '~/queries/schema/schema-general'
import {
    filterForQuery,
    filterKeyForQuery,
    getAggregationGroupTypeIndex,
    getBreakdown,
    getCompareFilter,
    getDisplay,
    getFormula,
    getFormulaNodes,
    getFormulas,
    getGoalLines,
    getInterval,
    getLegendPosition,
    getResultCustomizationBy,
    getSeries,
    getShowAlertThresholdLines,
    getShowAnnotations,
    getShowLabelsOnSeries,
    getShowLegend,
    getShowMultipleYAxes,
    getShowPercentagesOnSeries,
    getShowPercentStackView,
    getShowValuesOnSeries,
    getYAxisScaleType,
    isActionsNode,
    isAnyDataWarehouseNode,
    isDataWarehouseNode,
    isEventsNode,
    isFunnelsQuery,
    isInsightQueryNode,
    isInsightVizNode,
    isLifecycleDataWarehouseNode,
    isLifecycleQuery,
    isNodeWithSource,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
    isWebAnalyticsInsightQuery,
    isWebOverviewQuery,
    isWebStatsTableQuery,
    nodeKindToFilterProperty,
    supportsBarValueStacking,
    supportsPercentStackView,
} from '~/queries/utils'
import {
    BaseMathType,
    ChartDisplayType,
    FunnelVizType,
    InsightLogicProps,
    LabelGroupType,
    SlowQueryPossibilities,
} from '~/types'

import type { insightVizDataLogicType } from './insightVizDataLogicType'

const SHOW_TIMEOUT_MESSAGE_AFTER = 5000

// Trends/stickiness displays whose chart renders the in-chart quill legend (line/area/cumulative
// and bar layouts). Lifecycle always renders it regardless of display.
const DISPLAYS_WITH_IN_CHART_LEGEND = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsUnstackedBar,
]

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
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            insightDataLogic,
            ['setQuery', 'setInsightData', 'loadData', 'loadDataSuccess', 'loadDataFailure', 'cancelChanges'],
        ],
    })),

    actions({
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        updateQuerySource: (querySource: QuerySourceUpdate) => ({ querySource }),
        updateInsightFilter: (insightFilter: InsightFilter) => ({ insightFilter }),
        updateDateRange: (dateRange: DateRange, ignoreDebounce: boolean = false) => ({ dateRange, ignoreDebounce }),
        /** Apply a drag-to-zoom date range to the insight's query. */
        zoomDateRange: (dateFrom: string, dateTo: string) => ({ dateFrom, dateTo }),
        updateBreakdownFilter: (breakdownFilter: BreakdownFilter) => ({ breakdownFilter }),
        updateCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        updateDisplay: (display: ChartDisplayType | undefined) => ({ display }),
        setTimedOutQueryId: (id: string | null) => ({ id }),
        setIsIntervalManuallySet: (isIntervalManuallySet: boolean) => ({ isIntervalManuallySet }),
        toggleFormulaMode: true,
        removeFormulaNode: (formulas: TrendsFormulaNode[]) => ({ formulas }),
        setDetailedResultsAggregationType: (detailedResultsAggregationType: AggregationType) => ({
            detailedResultsAggregationType,
        }),
        updateVizSpecificOptions: (vizSpecificOptions: VizSpecificOptions) => ({ vizSpecificOptions }),
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
            (query) => {
                if (!isNodeWithSource(query) || !isInsightQueryNode(query.source)) {
                    return null
                }

                const source = query.source

                // Clean up Web Analytics queries by removing invalid fields that might have been saved
                if (isWebStatsTableQuery(source) || isWebOverviewQuery(source)) {
                    const { series, breakdownFilter, ...cleanSource } = source as typeof source & {
                        series?: unknown
                        breakdownFilter?: unknown
                    }
                    return cleanSource as typeof source
                }

                return source
            },
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
        isWebStatsTable: [(s) => [s.querySource], (q) => isWebStatsTableQuery(q)],
        isWebOverview: [(s) => [s.querySource], (q) => isWebOverviewQuery(q)],
        isWebAnalytics: [(s) => [s.querySource], (q) => isWebAnalyticsInsightQuery(q)],
        isTrendsLike: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isLifecycleQuery(q) || isStickinessQuery(q)], // this is for filtering out world map
        supportsDisplay: [(s) => [s.querySource], (q) => isTrendsQuery(q) || isStickinessQuery(q)],
        supportsCompare: [
            (s) => [s.querySource, s.display, s.dateRange, s.featureFlags],
            (q, display, dateRange, featureFlags) => {
                if (dateRange?.date_from === 'all') {
                    return false
                }
                if (isTrendsQuery(q) || isStickinessQuery(q) || isWebAnalyticsInsightQuery(q)) {
                    return display !== ChartDisplayType.WorldMap && display !== ChartDisplayType.CalendarHeatmap
                }
                // Funnel compare ships behind a flag, for the STEPS, TRENDS and TIME_TO_CONVERT viz
                // modes. FLOW is excluded — the backend ignores compare for it (mirrors `_is_compare_active`).
                if (isFunnelsQuery(q) && !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNELS_COMPARE]) {
                    return (q.funnelsFilter?.funnelVizType ?? FunnelVizType.Steps) !== FunnelVizType.Flow
                }
                return false
            },
        ],
        supportsPercentStackView: [(s) => [s.querySource], (q) => supportsPercentStackView(q)],
        supportsBarValueStacking: [(s) => [s.querySource], (q) => supportsBarValueStacking(q)],
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
        samplingFactor: [(s) => [s.querySource], (q) => (q && 'samplingFactor' in q ? q.samplingFactor : null)],
        showAlertThresholdLines: [(s) => [s.querySource], (q) => (q ? getShowAlertThresholdLines(q) : null)],
        showAnnotations: [(s) => [s.querySource], (q) => (q ? getShowAnnotations(q) : null)],
        showLegend: [(s) => [s.querySource], (q) => (q ? getShowLegend(q) : null)],
        legendPosition: [(s) => [s.querySource], (q) => (q ? getLegendPosition(q) : null)],
        showValuesOnSeries: [(s) => [s.querySource], (q) => (q ? getShowValuesOnSeries(q) : null)],
        showPercentagesOnSeries: [(s) => [s.querySource], (q) => (q ? getShowPercentagesOnSeries(q) : null)],
        showLabelOnSeries: [(s) => [s.querySource], (q) => (q ? getShowLabelsOnSeries(q) : null)],
        showPercentStackView: [(s) => [s.querySource], (q) => (q ? getShowPercentStackView(q) : null)],
        yAxisScaleType: [(s) => [s.querySource], (q) => (q ? getYAxisScaleType(q) : null)],
        showMultipleYAxes: [(s) => [s.querySource], (q) => (q ? getShowMultipleYAxes(q) : null)],
        resultCustomizationBy: [(s) => [s.querySource], (q) => (q ? getResultCustomizationBy(q) : null)],
        aggregationGroupTypeIndex: [(s) => [s.querySource], (q) => (q ? getAggregationGroupTypeIndex(q) : null)],
        labelGroupType: [
            (s) => [s.aggregationGroupTypeIndex],
            (aggregationGroupTypeIndex): LabelGroupType => aggregationGroupTypeIndex ?? 'people',
        ],
        goalLines: [
            (s) => [s.querySource],
            (q) => (isTrendsQuery(q) || isFunnelsQuery(q) || isRetentionQuery(q) ? getGoalLines(q) : null),
        ],
        insightFilter: [
            (s) => [s.querySource],
            (q) => (q && !isWebAnalyticsInsightQuery(q) ? filterForQuery(q) : null),
        ],
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

        // Whether the insight will produce a single visual output (one line/bar).
        // Considers breakdowns: a breakdown splits one series into multiple visual outputs.
        // See also: isSingleSeriesDefinition (which ignores breakdowns).
        isSingleSeriesOutput: [
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
                return !!breakdownFilter?.breakdown || (breakdownFilter?.breakdowns?.length ?? 0) > 0
            },
        ],

        // Whether there's only one event/action series defined in the query.
        // Ignores breakdowns which create multiple visual outputs from the same series.
        // See also: isSingleSeriesOutput (which considers breakdowns).
        isSingleSeriesDefinition: [
            (s) => [s.isTrends, s.formula, s.formulas, s.formulaNodes, s.series],
            (
                isTrends: boolean,
                formula: string | undefined,
                formulas: string[] | undefined,
                formulaNodes: TrendsFormulaNode[] | undefined,
                series: any[]
            ): boolean => {
                const hasSingleFormula =
                    (formula && !formulas) ||
                    (formulas && formulas.length === 1) ||
                    (formulaNodes && formulaNodes.length === 1)
                return (isTrends && hasSingleFormula) || (series || []).length <= 1
            },
        ],

        hasDataWarehouseSeries: [
            (s) => [s.series],
            (series): boolean => (series || []).length > 0 && !!series?.some((node) => isAnyDataWarehouseNode(node)),
        ],
        hasOnlyDataWarehouseSeries: [
            (s) => [s.series],
            (series): boolean => {
                return !!series && series.length > 0 && series.every((node) => isAnyDataWarehouseNode(node))
            },
        ],

        currentDataWarehouseSchemaColumns: [
            (s) => [
                s.series,
                s.isSingleSeriesOutput,
                s.isTrends,
                s.hasDataWarehouseSeries,
                s.isBreakdownSeries,
                s.dataWarehouseTablesMap,
            ],
            (
                series,
                isSingleSeriesOutput,
                isTrends,
                hasDataWarehouseSeries,
                isBreakdownSeries,
                dataWarehouseTablesMap
            ): DatabaseSchemaField[] => {
                if (!hasDataWarehouseSeries || (isTrends && !isSingleSeriesOutput && !isBreakdownSeries)) {
                    return []
                }

                const dataWarehouseSeries = series!.filter(isAnyDataWarehouseNode)
                const dataWarehouseTableNames = Array.from(new Set(dataWarehouseSeries.map((node) => node.table_name)))
                return dataWarehouseTableNames.flatMap((tableName) =>
                    Object.values(dataWarehouseTablesMap[tableName]?.fields ?? {})
                )
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

        // Whether the active chart renders the unified in-chart quill legend (replacing the legacy
        // side legend) instead of the legacy show/hide checkbox. Single source of truth shared by
        // InsightDisplayConfig (which control to show) and InsightVizDisplay (suppress side legend).
        usesInChartLegend: [
            (s) => [s.featureFlags, s.isTrends, s.isStickiness, s.isLifecycle, s.display],
            (featureFlags, isTrends, isStickiness, isLifecycle, display): boolean => {
                // Lifecycle always uses config.legend inside TimeSeriesBarChart — no flag gate needed.
                if (isLifecycle) {
                    return true
                }
                if (!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_LEGEND]) {
                    return false
                }
                return (isTrends || isStickiness) && (!display || DISPLAYS_WITH_IN_CHART_LEGEND.includes(display))
            },
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
            (s) => [s.activeUsersMath, s.isTrends, s.featureFlags],
            (activeUsersMath, isTrends, featureFlags): Intervals => {
                const enabledIntervals: Intervals = { ...intervals }

                if (featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_QUARTER_YEAR_INTERVALS]) {
                    enabledIntervals.quarter = { ...enabledIntervals.quarter, hidden: false }
                    enabledIntervals.year = { ...enabledIntervals.year, hidden: false }
                }

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
                        enabledIntervals.quarter = {
                            ...enabledIntervals.quarter,
                            disabledReason:
                                'Grouping by quarter is not supported on insights with weekly active users series.',
                        }
                        enabledIntervals.year = {
                            ...enabledIntervals.year,
                            disabledReason:
                                'Grouping by year is not supported on insights with weekly active users series.',
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
        validationErrorCode: [
            (s) => [s.insightDataError],
            (insightDataError): string | null => extractValidationErrorCode(insightDataError),
        ],

        timezone: [(s) => [s.insightData], (insightData) => insightData?.timezone || 'UTC'],

        // all events used in the insight (useful for fetching only relevant property definitions)
        allEventNames: [
            (s) => [s.querySource, actionsModel.selectors.actions],
            (querySource, actions) => (querySource ? getAllEventNames(querySource, actions) : []),
        ],

        theme: [
            (s) => [s.getTheme, s.querySource],
            (getTheme, querySource) =>
                getTheme(querySource && 'dataColorTheme' in querySource ? querySource.dataColorTheme : undefined),
        ],

        isAllEventsQuery: [
            (s) => [s.querySource],
            (querySource) => {
                return (
                    (querySource?.kind === NodeKind.TrendsQuery || querySource?.kind === NodeKind.FunnelsQuery) &&
                    querySource?.series?.some((s: { name?: string }) => s.name === 'All events')
                )
            },
        ],
        isFirstTimeForUserQuery: [
            (s) => [s.querySource],
            (querySource) => {
                return (
                    querySource?.kind === NodeKind.TrendsQuery &&
                    querySource?.series?.some((s: { math?: string }) =>
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

    listeners(({ actions, values, props, cache }) => ({
        // query
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                if (props.setQuery) {
                    props.setQuery(query)
                }
            }
        },

        // Discarding edits reverts the query to the saved version. A debounced filter
        // update (e.g. updateDateRange) that was dispatched just before the discard would
        // otherwise resolve afterwards and re-apply the discarded value on top of the
        // reverted query. Flag it so the in-flight debounce bails out instead.
        cancelChanges: () => {
            cache.pendingFilterUpdateCancelled = true
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

        zoomDateRange: ({ dateFrom, dateTo }) => {
            // Sub-day buckets carry a time component; explicitDate stops the backend from
            // rounding them back out to whole days.
            actions.updateDateRange(
                { date_from: dateFrom, date_to: dateTo, explicitDate: hasTimeComponent(dateFrom) },
                true
            )
        },

        // query source properties
        updateDateRange: async ({ dateRange, ignoreDebounce }, breakpoint) => {
            cache.pendingFilterUpdateCancelled = false
            if (!ignoreDebounce) {
                await breakpoint(300)
            }
            // Changes were discarded while this debounce was pending — don't re-apply the
            // edited date range over the query that cancelChanges just reverted.
            if (cache.pendingFilterUpdateCancelled) {
                cache.pendingFilterUpdateCancelled = false
                return
            }
            eventUsageLogic.actions.reportInsightDateRangeChanged(values.querySource?.kind)
            const updates = {
                dateRange: {
                    ...values.dateRange,
                    ...dateRange,
                    explicitDate: dateRange.explicitDate ?? values.dateRange?.explicitDate ?? false,
                },
                ...(dateRange.date_from == 'all' ? ({ compareFilter: undefined } as Partial<TrendsQuery>) : {}),
            } as QuerySourceUpdate

            // Reset selectedInterval for retention insights when date range changes
            if (values.isRetention && !isWebAnalyticsInsightQuery(values.localQuerySource)) {
                const filterProperty = filterKeyForQuery(values.localQuerySource)
                Object.assign(updates, {
                    [filterProperty]: { ...filterForQuery(values.localQuerySource), selectedInterval: null },
                })
            }

            actions.updateQuerySource(updates)
        },
        setExplicitDate: ({ explicitDate }) => {
            actions.updateQuerySource({
                dateRange: {
                    ...values.dateRange,
                    explicitDate,
                },
            })
        },
        updateBreakdownFilter: async ({ breakdownFilter }, breakpoint) => {
            await breakpoint(500) // extra debounce time because of number input
            eventUsageLogic.actions.reportInsightBreakdownChanged(values.querySource?.kind)
            const update: Partial<TrendsQuery> = { breakdownFilter: { ...values.breakdownFilter, ...breakdownFilter } }
            actions.updateQuerySource(update)
        },
        updateCompareFilter: async ({ compareFilter }, breakpoint) => {
            await breakpoint(500) // extra debounce time because of number input
            eventUsageLogic.actions.reportInsightCompareChanged(values.querySource?.kind)
            const update: Partial<TrendsQuery> = { compareFilter: { ...values.compareFilter, ...compareFilter } }
            actions.updateQuerySource(update)
        },

        // insight filter
        updateInsightFilter: async ({ insightFilter }, breakpoint) => {
            // When an external save handler is wired (dashboard card), skip the debounce so
            // rapid successive toggle clicks don't cancel each other and lose earlier changes.
            if (!props.setQuery) {
                await breakpoint(300)
            }

            if (isWebAnalyticsInsightQuery(values.localQuerySource)) {
                return
            }

            const filterProperty = filterKeyForQuery(values.localQuerySource)
            actions.updateQuerySource({
                [filterProperty]: { ...filterForQuery(values.localQuerySource), ...insightFilter },
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

        updateVizSpecificOptions: ({ vizSpecificOptions }) => {
            actions.setQuery({
                ...values.query,
                vizSpecificOptions: {
                    ...values.vizSpecificOptions,
                    ...vizSpecificOptions,
                },
            } as Node)
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
        removeFormulaNode: ({ formulas }) => {
            if (formulas.length === 0) {
                actions.toggleFormulaMode()
                return
            }

            const filledFormulas = formulas.filter((v) => v.formula.trim() !== '')
            if (filledFormulas.length > 0) {
                actions.updateInsightFilter({
                    formula: undefined,
                    formulas: undefined,
                    formulaNodes: filledFormulas,
                })
            }
        },
    })),
])

const getActiveUsersMath = (
    series: (AnyEntityNode<AnyDataWarehouseNode> | GroupNode<AnyDataWarehouseNode>)[] | null | undefined
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

/** Whether a date string carries a time of day, e.g. drag-to-zoom on an hourly chart emits
 *  `2024-06-10 08:00:00`. A bare `YYYY-MM-DD` means "that whole day". */
export function hasTimeComponent(date: string): boolean {
    return /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(date)
}

const handleQuerySourceUpdateSideEffects = (
    update: QuerySourceUpdate,
    currentState: InsightQueryNode,
    isIntervalManuallySet: boolean
): QuerySourceUpdate => {
    const mergedUpdate = { ...update } as InsightQueryNode

    const maybeChangedSeries = (update as TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery).series || null
    const maybeChangedActiveUsersMath = maybeChangedSeries ? getActiveUsersMath(maybeChangedSeries) : null
    const kind = (update as Partial<InsightQueryNode>).kind || currentState.kind
    const insightFilter = filterForQuery(currentState as ProductAnalyticsInsightQueryNode) as Partial<InsightFilter>
    const maybeChangedInsightFilter = (update as Record<string, InsightFilter | undefined>)[
        (nodeKindToFilterProperty as Record<string, InsightFilterProperty>)[kind]
    ] as Partial<InsightFilter>

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
        (interval === 'hour' ||
            interval === 'month' ||
            interval === 'minute' ||
            interval === 'quarter' ||
            interval === 'year')
    ) {
        if (interval === 'hour' || interval === 'minute') {
            lemonToast.info(
                `Switched to grouping by day, because "${BASE_MATH_DEFINITIONS[maybeChangedActiveUsersMath].name}" does not support grouping by ${interval}.`
            )
            ;(mergedUpdate as TrendsQuery).interval = 'day'
        } else if (maybeChangedActiveUsersMath === BaseMathType.WeeklyActiveUsers) {
            lemonToast.info(
                `Switched to grouping by week, because "${BASE_MATH_DEFINITIONS[maybeChangedActiveUsersMath].name}" does not support grouping by ${interval}.`
            )
            ;(mergedUpdate as TrendsQuery).interval = 'week'
        }
    }

    // clamp the funnel conversion window and per-exclusion step ranges against the new series
    if (maybeChangedSeries && isFunnelsQuery(currentState)) {
        const funnelsFilter = insightFilter as FunnelsFilter | undefined
        const hasConversionWindow = funnelsFilter?.funnelFromStep != null || funnelsFilter?.funnelToStep != null
        const hasExclusions = (funnelsFilter?.exclusions?.length ?? 0) > 0

        if (hasConversionWindow || hasExclusions) {
            // Filter out GroupNode types as funnels only use AnyEntityNode
            const funnelSeries: AnyEntityNode<FunnelsDataWarehouseNode>[] = maybeChangedSeries.filter(
                (node): node is AnyEntityNode<FunnelsDataWarehouseNode> => node.kind !== NodeKind.GroupNode
            )
            ;(mergedUpdate as FunnelsQuery).funnelsFilter = {
                ...funnelsFilter,
                ...getClampedFunnelStepRange(funnelsFilter ?? {}, funnelSeries),
                ...(hasExclusions
                    ? {
                          exclusions: funnelsFilter?.exclusions?.map((exclusion) => ({
                              ...exclusion,
                              ...getClampedFunnelStepRange(exclusion, funnelSeries),
                          })),
                      }
                    : {}),
            }
        }
    }

    if (
        maybeChangedSeries &&
        isLifecycleQuery(currentState) &&
        currentState.customAggregationTarget &&
        !maybeChangedSeries.some((series) => isLifecycleDataWarehouseNode(series))
    ) {
        ;(mergedUpdate as LifecycleQuery).customAggregationTarget = undefined
    }

    if (
        maybeChangedSeries &&
        isLifecycleQuery(currentState) &&
        maybeChangedSeries.some((series) => isLifecycleDataWarehouseNode(series))
    ) {
        ;(mergedUpdate as LifecycleQuery).properties = undefined
        ;(mergedUpdate as LifecycleQuery).filterTestAccounts = false
        ;(mergedUpdate as LifecycleQuery).samplingFactor = undefined
    }

    // We do not support properties, filtering test accounts, and sampling for DWH nodes
    // Disable them if there are any
    if (
        isTrendsQuery(currentState) &&
        (currentState.filterTestAccounts || currentState.properties) &&
        maybeChangedSeries?.some(isAnyDataWarehouseNode)
    ) {
        lemonToast.info(
            'Filter groups and test accounts are not supported for Data Warehouse series and have been disabled.'
        )

        ;(mergedUpdate as TrendsQuery).properties = undefined
        ;(mergedUpdate as TrendsQuery).filterTestAccounts = false
        ;(mergedUpdate as TrendsQuery).samplingFactor = undefined
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
            const quarterYearEnabled =
                !!featureFlagLogic.findMounted()?.values.featureFlags[
                    FEATURE_FLAGS.PRODUCT_ANALYTICS_QUARTER_YEAR_INTERVALS
                ]
            const parsedFrom = dayjs(date_from)
            const parsedTo = dayjs(date_to)
            const monthDiff = parsedTo.diff(parsedFrom, 'month')
            // 3 years in months; quarter auto-interval kicks in beyond this threshold
            const QUARTER_AUTO_INTERVAL_THRESHOLD_MONTHS = 36
            // A bare date pair like 2024-06-10..2024-06-10 means "that whole day", so only ranges
            // that carry a time component (e.g. drag-to-zoom on an hourly chart) can go sub-hour.
            const rangeHasTime = hasTimeComponent(String(date_from)) || hasTimeComponent(String(date_to))
            if (isTrendsQuery(currentState) && rangeHasTime && parsedTo.diff(parsedFrom, 'hour', true) <= 12) {
                // Mirrors the is12HoursOrLess rule for relative ranges below.
                ;(mergedUpdate as TrendsQuery).interval = 'minute'
            } else if (parsedTo.diff(parsedFrom, 'day') <= 3) {
                ;(mergedUpdate as TrendsQuery).interval = 'hour'
            } else if (monthDiff <= 3) {
                ;(mergedUpdate as TrendsQuery).interval = 'day'
            } else if (quarterYearEnabled && monthDiff > QUARTER_AUTO_INTERVAL_THRESHOLD_MONTHS) {
                ;(mergedUpdate as TrendsQuery).interval = 'quarter'
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
        const math = (maybeChangedSeries || (currentState as TrendsQuery).series)?.[0]?.math

        ;(mergedUpdate as TrendsQuery).breakdownFilter = {
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
        ;(mergedUpdate as TrendsQuery).breakdownFilter = undefined
        mergedUpdate['properties'] = []
    }

    // Remove breakdown filter if display type is BoldNumber because it is not supported
    if (kind === NodeKind.TrendsQuery && maybeChangedDisplay === ChartDisplayType.BoldNumber) {
        ;(mergedUpdate as TrendsQuery).breakdownFilter = undefined
    }

    // Remove breakdown filter if display type is Metric because it is single-series
    if (kind === NodeKind.TrendsQuery && maybeChangedDisplay === ChartDisplayType.Metric) {
        ;(mergedUpdate as TrendsQuery).breakdownFilter = undefined
    }

    // Remove breakdown filter if display type is Heatmap because it is not supported
    if (kind === NodeKind.TrendsQuery && maybeChangedDisplay === ChartDisplayType.CalendarHeatmap) {
        ;(mergedUpdate as TrendsQuery).breakdownFilter = undefined
    }

    // Remove formulas for box plot (formulas don't apply to statistical distributions)
    if (kind === NodeKind.TrendsQuery && maybeChangedDisplay === ChartDisplayType.BoxPlot) {
        ;(mergedUpdate as TrendsQuery).breakdownFilter = undefined
        ;(mergedUpdate as TrendsQuery).trendsFilter = {
            ...(mergedUpdate as TrendsQuery).trendsFilter,
            formula: undefined,
            formulas: undefined,
            formulaNodes: [],
        }
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
        const isAbsoluteRange = !!date_from && !!date_to && dayjs(date_from).isValid() && dayjs(date_to).isValid()

        if (
            // When insights are created, they might not have an explicit dateRange set. Change it to an hour if the interval is minute.
            (!date_from && !date_to) ||
            // If the interval is set manually to a range greater than 12 hours, change it to an hour
            (isAbsoluteRange && dayjs(date_to).diff(dayjs(date_from), 'hour') > 12) ||
            // Relative ranges (e.g. -7d) must be 12 hours or less; an absolute range that reaches
            // here already passed the >12h check above, so it stays (is12HoursOrLess only parses
            // relative strings and would wrongly reset it).
            (!isAbsoluteRange && !is12HoursOrLess(date_from))
        ) {
            ;(mergedUpdate as TrendsQuery).dateRange = oneHourDateRange
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

    /*
     * Retention side effects
     */
    if (kind === NodeKind.RetentionQuery) {
        const retentionFilter = (mergedUpdate as RetentionQuery).retentionFilter
        if (retentionFilter?.timeWindowMode === '24_hour_windows') {
            retentionFilter.cumulative = false
        }
    }

    return mergedUpdate
}
