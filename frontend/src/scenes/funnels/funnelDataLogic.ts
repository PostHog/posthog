import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { DataColorTheme, DataColorToken } from 'lib/colors'
import { BIN_COUNT_AUTO } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { average, percentage, sum } from 'lib/utils/numbers'
import { ensureStringIsNotBlank } from 'lib/utils/strings'
import {
    BreakdownColorConfig,
    computeTileFallbackTokens,
    findBreakdownColorConfig,
    getBreakdownPropertyKey,
} from 'scenes/dashboard/dashboardBreakdownColors'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { getColorFromToken } from 'scenes/dataThemeLogic'
import { AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE } from 'scenes/insights/filters/aggregationTargetUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    formatEventName,
    getFunnelDatasetKey,
    getFunnelDatasetPosition,
    getFunnelResultCustomization,
    getFunnelResultCustomizationColorToken,
} from 'scenes/insights/utils'

import { Noun, groupsModel } from '~/models/groupsModel'
import { seriesNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelExclusionSteps, InsightQueryNode } from '~/queries/schema/schema-general'
import { FunnelsFilter, FunnelsQuery, FunnelsQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isWebOverviewQuery, isWebStatsTableQuery } from '~/queries/utils'
import {
    FlattenedFunnelStepByBreakdown,
    EntityType,
    FunnelConversionWindow,
    FunnelConversionWindowTimeUnit,
    FunnelResultType,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    FunnelTimeConversionMetrics,
    FunnelVizType,
    FunnelsTimeConversionBins,
    HistogramGraphDatum,
    InsightLogicProps,
    InsightModel,
    InsightType,
    StepOrderValue,
    TrendResult,
    FilterType,
} from '~/types'

import type { FeatureFlagsSet } from '../../lib/logic/featureFlagLogic'
import type {
    AnyDataWarehouseNode,
    AnyEntityNode,
    BreakdownFilter,
    DataWarehouseNode,
    FunnelsQuerySeriesNodeUnion,
    GoalLine,
    GroupNode,
    InsightFilter,
    LifecycleQuery,
    PathsQuery,
    ResultCustomizationByValue,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
} from '../../queries/schema/schema-general'
import type { PathsV2Query } from '../../queries/schema/schema-general'
import type { BreakdownKeyType, FunnelStep, IntervalType, LabelGroupType } from '../../types'
import type { QuerySourceUpdate } from '../insights/insightVizDataLogic'
import {
    TIME_INTERVAL_BOUNDS,
    aggregateBreakdownCompareResult,
    aggregateBreakdownResult,
    aggregateFunnelCompareResult,
    aggregationLabelForHogQL,
    dimPreviousPeriodColor,
    flattenedStepsByBreakdown,
    flattenedStepsByBreakdownCompare,
    flattenedStepsByCompare,
    getIncompleteConversionWindowStartDate,
    getLastFilledStep,
    getReferenceStep,
    getVisibilityKey,
    isBreakdownFunnelResults,
    isFunnelStepsBreakdownCompareResult,
    isFunnelStepsCompareResult,
    isFunnelWithEnoughSteps,
    isFunnelWithIncompleteDataWarehouseStep,
    stepsWithConversionMetrics,
} from './funnelUtils'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

/** A time-to-convert bins payload tagged with its compare period (present only when comparing). */
type TimeToConvertCompareBins = FunnelsTimeConversionBins & { compare_label?: 'current' | 'previous' }

/** Maps a time-to-convert bins payload onto histogram data. Returns null for too-few bins, [] when
 * nobody converted. Shared between the current and previous (compare) periods. */
function timeConversionBinsToHistogramData(
    timeConversionResults: FunnelsTimeConversionBins | null
): HistogramGraphDatum[] | null {
    if ((timeConversionResults?.bins?.length ?? 0) < 2) {
        return null // There are no results
    }

    const totalCount = sum(timeConversionResults!.bins.map(([, count]) => count))
    if (totalCount === 0) {
        return [] // Nobody has converted in the time period
    }

    const binSize = timeConversionResults!.bins[1][0] - timeConversionResults!.bins[0][0]
    return timeConversionResults!.bins.map(([id, count]: [id: number, count: number]) => {
        const value = Math.max(0, id)
        const percent = count / totalCount
        return {
            id: value,
            bin0: value,
            bin1: value + binSize,
            count,
            label: percent === 0 ? '' : percentage(percent, 1, true),
        }
    })
}

function getStepMetric(step: FunnelStepWithConversionMetrics | undefined, metric: string): number {
    if (!step) {
        return 0
    }
    switch (metric) {
        case 'conversion':
            return step.count ?? 0
        case 'dropoff':
            return step.droppedOffFromPrevious ?? 0
        case 'conversion_so_far':
            return step.conversionRates?.total ?? 0
        case 'conversion_from_prev':
            return step.conversionRates?.fromPrevious ?? 0
        case 'median_time':
            return step.median_conversion_time ?? 0
        case 'average_time':
            return step.average_conversion_time ?? 0
        default:
            return 0
    }
}

function compareBreakdownsByColumnKey(
    a: FlattenedFunnelStepByBreakdown,
    b: FlattenedFunnelStepByBreakdown,
    columnKey: string
): number {
    if (columnKey === 'breakdown_value') {
        const aVal =
            Array.isArray(a.breakdown_value) && a.breakdown_value.length > 0 ? a.breakdown_value[0] : a.breakdown_value
        const bVal =
            Array.isArray(b.breakdown_value) && b.breakdown_value.length > 0 ? b.breakdown_value[0] : b.breakdown_value
        if (typeof aVal === 'number' && typeof bVal === 'number') {
            return aVal - bVal
        }
        return String(aVal ?? '').localeCompare(String(bVal ?? ''))
    }
    if (columnKey === 'total_conversion') {
        return (a.conversionRates?.total ?? 0) - (b.conversionRates?.total ?? 0)
    }
    const stepMatch = columnKey.match(/^step_(\d+)_(.+)$/)
    if (stepMatch) {
        return (
            getStepMetric(a.steps?.[parseInt(stepMatch[1])], stepMatch[2]) -
            getStepMetric(b.steps?.[parseInt(stepMatch[1])], stepMatch[2])
        )
    }
    return 0
}

function isFunnelsQueryOrLegacyFilter(
    insightData: Partial<InsightModel> | null | undefined,
    querySource: InsightQueryNode | null
): boolean {
    /**
     * TODO: Remove legacy filter check once all tests are migrated to query-based format.
     * There are still multiple tests relying on the legacy format in funnelDataLogic.test.ts.
     */
    if (insightData?.filters?.insight === InsightType.FUNNELS) {
        return true
    }
    return isFunnelsQuery(querySource)
}

/**
 * The display override a series carries. `custom_name` is set by the "Rename graph series" modal; a
 * `name` that differs from the raw label is a rename applied through the query editor or the API.
 * Mirrors `resolve_series_custom_name` in `query_runner.py`, which the backend runs for trends only.
 *
 * `rawLabel` is the label the series shows without an override. Pass null when there is none to
 * compare against — a `name` is then indistinguishable from a default, so only `custom_name` counts.
 */
function resolveSeriesCustomName(node: FunnelsQuerySeriesNodeUnion, rawLabel: string | null): string | null {
    const customName = ensureStringIsNotBlank(node.custom_name)
    if (customName) {
        return customName
    }
    // An action resolves its name from the database at query time, so a stored copy can be stale. A
    // group composes its name from its members (`actionFilterGroupLogic`), so it is not typed by a
    // person either. Neither is evidence of a rename; both rename through `custom_name`.
    if (node.kind === NodeKind.ActionsNode || node.kind === NodeKind.GroupNode) {
        return null
    }
    const name = ensureStringIsNotBlank(node.name)
    // The picker writes the raw event key as `name`, and defaults write the label the UI renders it
    // as, so a `name` matching either form is the default rather than a rename.
    if (!name || rawLabel === null || name === rawLabel || name === formatEventName(rawLabel)) {
        return null
    }
    return name
}

/**
 * Whether a result step is still the one its series node describes. Results outlive the query that
 * produced them, so a step the node has moved off carries a label from the previous run.
 */
function describesStep(node: FunnelsQuerySeriesNodeUnion, step: FunnelStepWithNestedBreakdown): boolean {
    if (node.kind === NodeKind.EventsNode) {
        return step.action_id === (node.event ?? null)
    }
    if (node.kind === NodeKind.FunnelsDataWarehouseNode) {
        return step.name === node.table_name
    }
    return true
}

/**
 * Cached results carry the step names from the run that produced them, so a step renamed since then
 * renders under its old label. Mirrors `_apply_funnels_custom_names` in `query_runner.py`, which the
 * stored-result path bypasses: the query wins in both directions. A cleared `custom_name` falls back
 * to a `name` override, and blanks the label only when `name` matches the raw key. The `name` half is
 * a widening `_apply_funnels_custom_names` does not yet share, so backend-rendered surfaces — CSV
 * exports and API consumers reading `results[].custom_name` — keep the raw label until it does.
 * Unordered funnels are exempt because they label steps by position, not by series.
 */
function applyQueryStepCustomNames(
    steps: FunnelStepWithNestedBreakdown[],
    querySource: FunnelsQuery | null
): FunnelStepWithNestedBreakdown[] {
    if (!querySource?.series?.length || querySource.funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED) {
        return steps
    }

    let changed = false
    const renamed = steps.map((step) => {
        const node = querySource.series[step.order]
        if (!node) {
            return step
        }

        // An all-events step serializes with a null name; the UI renders it as "All events", so that
        // is the raw label a rename is compared against, matching trends and the backend serializer.
        const rawLabel = node.kind === NodeKind.EventsNode && node.event == null ? 'All events' : step.name
        const customName = resolveSeriesCustomName(node, describesStep(node, step) ? rawLabel : null)
        // Nested rows are breakdown or compare variants of the same step, so they take the parent's
        // name. Their own `order` can hold a breakdown rank, which is not a series index.
        const nested = step.nested_breakdown?.map((row) =>
            row.custom_name === customName ? row : { ...row, custom_name: customName }
        )
        const nestedChanged = nested?.some((row, i) => row !== step.nested_breakdown?.[i])
        if (customName === step.custom_name && !nestedChanged) {
            return step
        }

        changed = true
        return { ...step, custom_name: customName, ...(nested ? { nested_breakdown: nested } : {}) }
    })
    return changed ? renamed : steps
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface funnelDataLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun // groupsModel
    breakdownFilter: BreakdownFilter | null | undefined // insightVizDataLogic
    funnelsFilter: FunnelsFilter | null | undefined // insightVizDataLogic
    getTheme: (themeId: number | string | null | undefined) => DataColorTheme | null // insightVizDataLogic
    goalLines: GoalLine[] | null | undefined // insightVizDataLogic
    hasDataWarehouseSeries: boolean // insightVizDataLogic
    insightData: Record<string, any> // insightVizDataLogic
    insightDataError: Record<string, any> | null // insightVizDataLogic
    insightFilter: InsightFilter | null | undefined // insightVizDataLogic
    interval: IntervalType | null | undefined // insightVizDataLogic
    labelGroupType: LabelGroupType // insightVizDataLogic
    legendPosition: string | null | undefined // insightVizDataLogic
    showLegend: boolean | null | undefined // insightVizDataLogic
    showValuesOnSeries: boolean | null | undefined // insightVizDataLogic
    vizQuerySource:
        | FunnelsQuery
        | LifecycleQuery
        | PathsQuery
        | PathsV2Query
        | RetentionQuery
        | StickinessQuery
        | TrendsQuery
        | WebOverviewQuery
        | WebStatsTableQuery
        | null // insightVizDataLogic
    vizSeries: (AnyEntityNode<AnyDataWarehouseNode> | GroupNode<DataWarehouseNode>)[] | null | undefined // insightVizDataLogic
    advancedOptionsUsedCount: number
    aggregationTargetLabel: Noun
    breakdownSorting: string | undefined
    conversionMetrics: FunnelTimeConversionMetrics
    conversionWindow: Required<FunnelConversionWindow>
    conversionWindowInterval: number | null
    conversionWindowUnit: FunnelConversionWindowTimeUnit | null
    disableFunnelBreakdownBaseline: boolean
    exclusionDefaultStepRange: FunnelExclusionSteps
    exclusionFilters: FilterType
    flattenedBreakdowns: FlattenedFunnelStepByBreakdown[]
    funnelVizType: FunnelVizType
    getFunnelsColor: (dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics) => string
    getFunnelsColorToken: (
        dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
    ) => [DataColorTheme | null, DataColorToken | null]
    hasFunnelResults: boolean
    hiddenLegendBreakdowns: string[] | undefined
    histogramGraphData: HistogramGraphDatum[] | null
    histogramGraphDataPrevious: HistogramGraphDatum[] | null
    incompletenessOffsetFromEnd: number
    indexedSteps: {
        action_id: string
        average_conversion_time: number | null
        breakdown?: BreakdownKeyType | undefined
        breakdown_value?: BreakdownKeyType | undefined
        breakdowns?: BreakdownKeyType[] | undefined
        colorIndex: number
        compare: boolean | undefined
        compare_label?: 'current' | 'previous' | undefined
        converted_people_url: string
        count: number
        custom_name?: string | null | undefined
        data?: number[] | undefined
        days?: string[] | undefined
        dropped_people_url: string | null
        id: number
        labels?: string[] | undefined
        median_conversion_time: number | null
        name: string
        nested_breakdown?: FunnelStep[] | undefined
        order: number
        people?: string[] | undefined
        seriesIndex: number
        type: EntityType
    }[]
    isBreakdownCompareFunnel: boolean
    isComparedFunnel: boolean
    isEmptyFunnel: boolean | null
    isFunnelWithEnoughSteps: boolean
    isFunnelWithIncompleteDataWarehouseStep: boolean
    isSkewed: boolean
    isStepOptional: (step: number) => boolean
    isStepsFunnel: boolean | null
    isTimeToConvertFunnel: boolean | null
    isTrendsFunnel: boolean | null
    numericBinCount: number
    querySource: FunnelsQuery | null
    resultCustomizations: Record<string, ResultCustomizationByValue> | undefined
    results: FunnelResultType
    series: FunnelsQuerySeriesNodeUnion[] | null
    skewWarningHidden: boolean
    stepNames: FunnelStepWithNestedBreakdown[]
    steps: FunnelStepWithNestedBreakdown[]
    stepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    timeConversionResults: FunnelsTimeConversionBins | null
    timeConversionResultsPrevious: FunnelsTimeConversionBins | null
    visibleStepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface funnelDataLogicActions {
    cancelChanges: () => {
        value: true
    } // insightDataLogic
    updateInsightFilter: (insightFilter: InsightFilter) => {
        insightFilter: InsightFilter
    } // insightVizDataLogic
    updateQuerySource: (querySource: QuerySourceUpdate) => {
        querySource: QuerySourceUpdate
    } // insightVizDataLogic
    commitConversionWindow: () => {
        value: true
    }
    hideSkewWarning: () => {
        value: true
    }
    setBreakdownSorting: (breakdownSorting: string | undefined) => {
        breakdownSorting: string | undefined
    }
    setConversionWindowInterval: (funnelWindowInterval: number) => {
        funnelWindowInterval: number
    }
    setConversionWindowUnit: (funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit) => {
        funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit
    }
    setHiddenLegendBreakdowns: (hiddenLegendBreakdowns: string[]) => {
        hiddenLegendBreakdowns: string[]
    }
    toggleLegendBreakdownVisibility: (breakdown: string) => {
        breakdown: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface funnelDataLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        querySource: (
            vizQuerySource:
                | FunnelsQuery
                | LifecycleQuery
                | PathsQuery
                | PathsV2Query
                | RetentionQuery
                | StickinessQuery
                | TrendsQuery
                | WebOverviewQuery
                | WebStatsTableQuery
                | null
        ) => FunnelsQuery | null
        series: (
            vizQuerySource:
                | FunnelsQuery
                | LifecycleQuery
                | PathsQuery
                | PathsV2Query
                | RetentionQuery
                | StickinessQuery
                | TrendsQuery
                | WebOverviewQuery
                | WebStatsTableQuery
                | null,
            vizSeries: (AnyEntityNode<AnyDataWarehouseNode> | GroupNode<DataWarehouseNode>)[] | null | undefined
        ) => FunnelsQuerySeriesNodeUnion[] | null
        isStepsFunnel: (funnelsFilter: FunnelsFilter | null | undefined) => boolean | null
        isTimeToConvertFunnel: (funnelsFilter: FunnelsFilter | null | undefined) => boolean | null
        isTrendsFunnel: (funnelsFilter: FunnelsFilter | null | undefined) => boolean | null
        isEmptyFunnel: (querySource: FunnelsQuery | null) => boolean | null
        funnelVizType: (funnelsFilter: FunnelsFilter | null | undefined) => FunnelVizType
        aggregationTargetLabel: (
            querySource: FunnelsQuery | null,
            aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
        ) => Noun
        results: (
            insightData: Record<string, any>,
            vizQuerySource:
                | FunnelsQuery
                | LifecycleQuery
                | PathsQuery
                | PathsV2Query
                | RetentionQuery
                | StickinessQuery
                | TrendsQuery
                | WebOverviewQuery
                | WebStatsTableQuery
                | null,
            querySource: FunnelsQuery | null
        ) => FunnelResultType
        steps: (
            insightData: Record<string, any>,
            vizQuerySource:
                | FunnelsQuery
                | LifecycleQuery
                | PathsQuery
                | PathsV2Query
                | RetentionQuery
                | StickinessQuery
                | TrendsQuery
                | WebOverviewQuery
                | WebStatsTableQuery
                | null,
            querySource: FunnelsQuery | null,
            breakdownFilter: BreakdownFilter | null | undefined,
            results: FunnelResultType,
            isTimeToConvertFunnel: boolean | null,
            isStepsFunnel: boolean | null
        ) => FunnelStepWithNestedBreakdown[]
        stepNames: (querySource: FunnelsQuery | null) => FunnelStepWithNestedBreakdown[]
        isComparedFunnel: (steps: FunnelStepWithNestedBreakdown[]) => boolean
        isBreakdownCompareFunnel: (results: FunnelResultType, isStepsFunnel: boolean | null) => boolean
        stepsWithConversionMetrics: (
            steps: FunnelStepWithNestedBreakdown[],
            funnelsFilter: FunnelsFilter | null | undefined,
            querySource: FunnelsQuery | null
        ) => FunnelStepWithConversionMetrics[]
        disableFunnelBreakdownBaseline: (arg: any) => boolean
        flattenedBreakdowns: (
            stepsWithConversionMetrics: FunnelStepWithConversionMetrics[],
            funnelsFilter: FunnelsFilter | null | undefined,
            disableFunnelBreakdownBaseline: boolean,
            breakdownSorting: string | undefined,
            isComparedFunnel: boolean,
            isBreakdownCompareFunnel: boolean
        ) => FlattenedFunnelStepByBreakdown[]
        hiddenLegendBreakdowns: (funnelsFilter: FunnelsFilter | null | undefined) => string[] | undefined
        breakdownSorting: (funnelsFilter: FunnelsFilter | null | undefined) => string | undefined
        resultCustomizations: (
            funnelsFilter: FunnelsFilter | null | undefined
        ) => Record<string, ResultCustomizationByValue> | undefined
        visibleStepsWithConversionMetrics: (
            stepsWithConversionMetrics: FunnelStepWithConversionMetrics[],
            flattenedBreakdowns: FlattenedFunnelStepByBreakdown[],
            hiddenLegendBreakdowns: string[] | undefined,
            isComparedFunnel: boolean,
            isBreakdownCompareFunnel: boolean
        ) => FunnelStepWithConversionMetrics[]
        timeConversionResults: (
            results: FunnelResultType,
            funnelsFilter: FunnelsFilter | null | undefined
        ) => FunnelsTimeConversionBins | null
        timeConversionResultsPrevious: (
            results: FunnelResultType,
            funnelsFilter: FunnelsFilter | null | undefined
        ) => FunnelsTimeConversionBins | null
        histogramGraphData: (timeConversionResults: FunnelsTimeConversionBins | null) => HistogramGraphDatum[] | null
        histogramGraphDataPrevious: (
            timeConversionResultsPrevious: FunnelsTimeConversionBins | null
        ) => HistogramGraphDatum[] | null
        hasFunnelResults: (
            insightData: Record<string, any>,
            funnelsFilter: FunnelsFilter | null | undefined,
            steps: FunnelStepWithNestedBreakdown[],
            histogramGraphData: HistogramGraphDatum[] | null,
            querySource: FunnelsQuery | null,
            stepNames: FunnelStepWithNestedBreakdown[]
        ) => boolean
        numericBinCount: (
            funnelsFilter: FunnelsFilter | null | undefined,
            timeConversionResults: FunnelsTimeConversionBins | null
        ) => number
        conversionMetrics: (
            steps: FunnelStepWithNestedBreakdown[],
            funnelsFilter: FunnelsFilter | null | undefined,
            timeConversionResults: FunnelsTimeConversionBins | null,
            insightData: Record<string, any>
        ) => FunnelTimeConversionMetrics
        conversionWindow: (funnelsFilter: FunnelsFilter | null | undefined) => Required<FunnelConversionWindow>
        incompletenessOffsetFromEnd: (
            steps: FunnelStepWithNestedBreakdown[],
            conversionWindow: Required<FunnelConversionWindow>
        ) => number
        advancedOptionsUsedCount: (funnelsFilter: FunnelsFilter | null | undefined) => number
        isSkewed: (conversionMetrics: FunnelTimeConversionMetrics, skewWarningHidden: boolean) => boolean
        indexedSteps: (steps: FunnelStepWithNestedBreakdown[]) => {
            action_id: string
            average_conversion_time: number | null
            breakdown?: BreakdownKeyType | undefined
            breakdown_value?: BreakdownKeyType | undefined
            breakdowns?: BreakdownKeyType[] | undefined
            colorIndex: number
            compare: boolean | undefined
            compare_label?: 'current' | 'previous' | undefined
            converted_people_url: string
            count: number
            custom_name?: string | null | undefined
            data?: number[] | undefined
            days?: string[] | undefined
            dropped_people_url: string | null
            id: number
            labels?: string[] | undefined
            median_conversion_time: number | null
            name: string
            nested_breakdown?: FunnelStep[] | undefined
            order: number
            people?: string[] | undefined
            seriesIndex: number
            type: EntityType
        }[]
        getFunnelsColorToken: (
            resultCustomizations: Record<string, ResultCustomizationByValue> | undefined,
            getTheme: (themeId: number | string | null | undefined) => DataColorTheme | null,
            breakdownFilter: BreakdownFilter | null | undefined,
            querySource: FunnelsQuery | null,
            flattenedBreakdowns: FlattenedFunnelStepByBreakdown[],
            disableFunnelBreakdownBaseline: boolean
        ) => (
            dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
        ) => [DataColorTheme | null, DataColorToken | null]
        getFunnelsColor: (
            getFunnelsColorToken: (
                dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
            ) => [DataColorTheme | null, DataColorToken | null]
        ) => (dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics) => string
        isStepOptional: (querySource: FunnelsQuery | null) => (step: number) => boolean
        isFunnelWithEnoughSteps: (series: FunnelsQuerySeriesNodeUnion[] | null) => boolean
        isFunnelWithIncompleteDataWarehouseStep: (series: FunnelsQuerySeriesNodeUnion[] | null) => boolean
        exclusionDefaultStepRange: (querySource: FunnelsQuery | null) => FunnelExclusionSteps
        exclusionFilters: (funnelsFilter: FunnelsFilter | null | undefined) => FilterType
    }
}

export type funnelDataLogicType = MakeLogicType<
    funnelDataLogicValues,
    funnelDataLogicActions,
    InsightLogicProps,
    funnelDataLogicMeta
>

export const funnelDataLogic = kea<funnelDataLogicType>([
    path((key) => ['scenes', 'funnels', 'funnelDataLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            [
                'querySource as vizQuerySource',
                'insightFilter',
                'funnelsFilter',
                'breakdownFilter',
                'goalLines',
                'series as vizSeries',
                'interval',
                'insightData',
                'insightDataError',
                'getTheme',
                'showLegend',
                'legendPosition',
                'showValuesOnSeries',
                'hasDataWarehouseSeries',
                'labelGroupType',
            ],
            groupsModel,
            ['aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            insightVizDataLogic(props),
            ['updateInsightFilter', 'updateQuerySource'],
            insightDataLogic(props),
            ['cancelChanges'],
        ],
    })),

    actions({
        hideSkewWarning: true,
        setHiddenLegendBreakdowns: (hiddenLegendBreakdowns: string[]) => ({ hiddenLegendBreakdowns }),
        toggleLegendBreakdownVisibility: (breakdown: string) => ({ breakdown }),
        setBreakdownSorting: (breakdownSorting: string | undefined) => ({ breakdownSorting }),
        setConversionWindowInterval: (funnelWindowInterval: number) => ({ funnelWindowInterval }),
        setConversionWindowUnit: (funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit) => ({
            funnelWindowIntervalUnit,
        }),
        commitConversionWindow: true,
    }),

    reducers({
        skewWarningHidden: [
            false,
            {
                hideSkewWarning: () => true,
            },
        ],
        conversionWindowInterval: [
            null as number | null,
            {
                setConversionWindowInterval: (_, { funnelWindowInterval }) => funnelWindowInterval,
                cancelChanges: () => null,
            },
        ],
        conversionWindowUnit: [
            null as FunnelConversionWindowTimeUnit | null,
            {
                setConversionWindowUnit: (_, { funnelWindowIntervalUnit }) => funnelWindowIntervalUnit,
                cancelChanges: () => null,
            },
        ],
    }),

    selectors(({ props }) => ({
        querySource: [
            (s) => [s.vizQuerySource],
            (
                vizQuerySource:
                    | FunnelsQuery
                    | null
                    | import('~/queries/schema/schema-general').LifecycleQuery
                    | import('~/queries/schema/schema-general').PathsQuery
                    | import('~/queries/schema/schema-general').RetentionQuery
                    | import('~/queries/schema/schema-general').StickinessQuery
                    | import('~/queries/schema/schema-general').TrendsQuery
                    | import('~/queries/schema/schema-general').WebOverviewQuery
                    | import('~/queries/schema/schema-general').WebStatsTableQuery
            ) => (isFunnelsQuery(vizQuerySource) ? vizQuerySource : null),
        ],

        series: [
            (s) => [s.vizQuerySource, s.vizSeries],
            (
                vizQuerySource:
                    | FunnelsQuery
                    | null
                    | import('~/queries/schema/schema-general').LifecycleQuery
                    | import('~/queries/schema/schema-general').PathsQuery
                    | import('~/queries/schema/schema-general').RetentionQuery
                    | import('~/queries/schema/schema-general').StickinessQuery
                    | import('~/queries/schema/schema-general').TrendsQuery
                    | import('~/queries/schema/schema-general').WebOverviewQuery
                    | import('~/queries/schema/schema-general').WebStatsTableQuery,
                series:
                    | (
                          | import('~/queries/schema/schema-general').AnyEntityNode<
                                import('~/queries/schema/schema-general').AnyDataWarehouseNode
                            >
                          | import('~/queries/schema/schema-general').GroupNode<
                                import('~/queries/schema/schema-general').DataWarehouseNode
                            >
                      )[]
                    | null
                    | undefined
            ) => (isFunnelsQuery(vizQuerySource) ? (series as FunnelsQuery['series']) : null),
        ],

        isStepsFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): boolean | null => {
                return funnelsFilter === null
                    ? null
                    : (funnelsFilter?.funnelVizType ?? FunnelVizType.Steps) === FunnelVizType.Steps
            },
        ],
        isTimeToConvertFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): boolean | null => {
                return funnelsFilter === null ? null : funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert
            },
        ],
        isTrendsFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): boolean | null => {
                return funnelsFilter === null ? null : funnelsFilter?.funnelVizType === FunnelVizType.Trends
            },
        ],

        isEmptyFunnel: [
            (s) => [s.querySource],
            (q: FunnelsQuery | null): boolean | null => {
                return isFunnelsQuery(q)
                    ? q.series.filter((n) => n.kind === NodeKind.EventsNode || n.kind === NodeKind.ActionsNode)
                          .length === 0
                    : null
            },
        ],

        // Saved funnels can lack a viz type entirely: the backend relies on a schema default that never
        // reaches the stored JSON the frontend reads. Resolve it once so every consumer agrees.
        funnelVizType: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): FunnelVizType =>
                funnelsFilter?.funnelVizType ?? FunnelVizType.Steps,
        ],

        aggregationTargetLabel: [
            (s) => [s.querySource, s.aggregationLabel],
            (
                querySource: FunnelsQuery | null,
                aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
            ): Noun => {
                if (!querySource) {
                    return { singular: '', plural: '' }
                }

                if (querySource.funnelsFilter?.customAggregationTarget) {
                    return AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE
                }

                return querySource.funnelsFilter?.funnelAggregateByHogQL
                    ? aggregationLabelForHogQL(querySource.funnelsFilter.funnelAggregateByHogQL)
                    : aggregationLabel(querySource.aggregation_group_type_index)
            },
        ],

        results: [
            (s) => [s.insightData, s.vizQuerySource, s.querySource],
            (
                insightData: Record<string, any>,
                vizQuerySource:
                    | FunnelsQuery
                    | null
                    | import('~/queries/schema/schema-general').LifecycleQuery
                    | import('~/queries/schema/schema-general').PathsQuery
                    | import('~/queries/schema/schema-general').RetentionQuery
                    | import('~/queries/schema/schema-general').StickinessQuery
                    | import('~/queries/schema/schema-general').TrendsQuery
                    | import('~/queries/schema/schema-general').WebOverviewQuery
                    | import('~/queries/schema/schema-general').WebStatsTableQuery,
                querySource: FunnelsQuery | null
            ): FunnelResultType => {
                // Web analytics queries should not be processed as funnels, even though their response
                // structure may look similar. InsightVizDisplay unconditionally mounts funnelDataLogic,
                // so we need explicit guards to prevent web analytics data from being misinterpreted.
                if (isWebStatsTableQuery(vizQuerySource) || isWebOverviewQuery(vizQuerySource)) {
                    return []
                }

                // TODO: after hooking up data manager, check that we have a funnels result here
                // We check both the legacy filter approach (insightData.filters.insight) and the new
                // query-based approach (querySource.kind) because tests still use the legacy approach.
                // This pattern matches the checks in the 'steps' and 'hasFunnelResults' selectors.
                if (
                    insightData?.filters?.insight !== InsightType.FUNNELS &&
                    querySource &&
                    querySource?.kind !== NodeKind.FunnelsQuery
                ) {
                    return []
                }

                if (insightData?.result) {
                    if (isBreakdownFunnelResults(insightData.result) && insightData.result?.[0]?.[0]?.breakdowns) {
                        // in order to stop the UI having to check breakdowns and breakdown
                        // this collapses breakdowns onto the breakdown property
                        return insightData.result.map((series) =>
                            series.map((step) => {
                                const { breakdowns, ...clone } = step
                                clone.breakdown = breakdowns as (string | number)[]
                                return clone
                            })
                        )
                    }
                    return insightData.result
                }
                return []
            },
        ],
        steps: [
            (s) => [
                s.insightData,
                s.vizQuerySource,
                s.querySource,
                s.breakdownFilter,
                s.results,
                s.isTimeToConvertFunnel,
                s.isStepsFunnel,
            ],
            (
                insightData: Record<string, any>,
                _vizQuerySource:
                    | FunnelsQuery
                    | null
                    | import('~/queries/schema/schema-general').LifecycleQuery
                    | import('~/queries/schema/schema-general').PathsQuery
                    | import('~/queries/schema/schema-general').RetentionQuery
                    | import('~/queries/schema/schema-general').StickinessQuery
                    | import('~/queries/schema/schema-general').TrendsQuery
                    | import('~/queries/schema/schema-general').WebOverviewQuery
                    | import('~/queries/schema/schema-general').WebStatsTableQuery,
                querySource: FunnelsQuery | null,
                breakdownFilter: null | import('~/queries/schema/schema-general').BreakdownFilter | undefined,
                results: FunnelResultType,
                isTimeToConvertFunnel: boolean | null,
                isStepsFunnel: boolean | null
            ): FunnelStepWithNestedBreakdown[] => {
                if (!isFunnelsQueryOrLegacyFilter(insightData, querySource)) {
                    return []
                }

                // we need to check whether results are an array, since isTimeToConvertFunnel can be false,
                // while still having "time-to-convert" results in insightData
                if (!isTimeToConvertFunnel && Array.isArray(results) && results.length > 0) {
                    // STEPS compare: the runner returns both periods' steps as a flat tagged list.
                    // Reshape into one step per order with current+previous as nested bars. Trends
                    // also tags rows with compare_label but renders via indexedSteps, so gate on STEPS.
                    if (isStepsFunnel && isFunnelStepsCompareResult(results)) {
                        return applyQueryStepCustomNames(aggregateFunnelCompareResult(results), querySource)
                    }
                    if (isBreakdownFunnelResults(results)) {
                        const breakdownProperty = breakdownFilter?.breakdowns
                            ? breakdownFilter?.breakdowns.map((b) => b.property).join('::')
                            : (breakdownFilter?.breakdown ?? undefined)
                        // Breakdown + compare: pair each breakdown value's current and previous
                        // funnels so the grouped bars share a color (previous desaturated). Must
                        // precede the plain breakdown path, which would otherwise treat each period
                        // as an independent breakdown value (and double-count the step aggregate).
                        if (isStepsFunnel && isFunnelStepsBreakdownCompareResult(results)) {
                            return applyQueryStepCustomNames(
                                aggregateBreakdownCompareResult(results, breakdownProperty),
                                querySource
                            )
                        }
                        return applyQueryStepCustomNames(
                            aggregateBreakdownResult(results, breakdownProperty).sort((a, b) => a.order - b.order),
                            querySource
                        )
                    }
                    return applyQueryStepCustomNames(
                        results.sort((a, b) => a.order - b.order),
                        querySource
                    )
                }

                return []
            },
        ],
        stepNames: [
            (s) => [s.querySource],
            (querySource: FunnelsQuery | null): FunnelStepWithNestedBreakdown[] => {
                if (!querySource?.series?.length) {
                    return []
                }

                return querySource.series.map((node, index) => {
                    // No results yet, so the raw label comes from the node itself rather than a step.
                    const rawLabel =
                        node.kind === NodeKind.ActionsNode
                            ? `Action ${node.id}`
                            : node.kind === NodeKind.EventsNode
                              ? (node.event ?? 'All events')
                              : null
                    // Same override rule the loaded steps use, so the label does not change on load.
                    const customName = resolveSeriesCustomName(node, rawLabel)
                    return {
                        action_id:
                            node.kind === NodeKind.ActionsNode
                                ? String(node.id)
                                : node.kind === NodeKind.EventsNode
                                  ? (node.event ?? '')
                                  : '',
                        name: customName || rawLabel || '',
                        custom_name: customName,
                        order: index,
                        count: 0,
                        type: (node.kind === NodeKind.ActionsNode ? 'actions' : 'events') as EntityType,
                        average_conversion_time: null,
                        median_conversion_time: null,
                        converted_people_url: '',
                        dropped_people_url: null,
                    }
                })
            },
        ],
        // True when STEPS results carry compare-tagged nested bars (current + previous per step).
        // Compare reshapes the data to look like a 2-value breakdown, so the breakdown baseline /
        // visibility machinery must be bypassed for it.
        isComparedFunnel: [
            (s) => [s.steps],
            (steps: FunnelStepWithNestedBreakdown[]): boolean =>
                Array.isArray(steps) &&
                steps.some((step) => step.nested_breakdown?.some((series) => series.compare_label != null)),
        ],
        // True when a compared funnel also carries real breakdown values (breakdown × compare), as
        // opposed to a pure compare funnel whose current/previous bars are not breakdown values.
        // Pure compare is then `isComparedFunnel && !isBreakdownCompareFunnel`: the former bypasses the
        // breakdown machinery entirely, the latter keeps it (table, hidden legend) around the grouped bars.
        isBreakdownCompareFunnel: [
            (s) => [s.results, s.isStepsFunnel],
            (results: FunnelResultType, isStepsFunnel: boolean | null): boolean =>
                !!isStepsFunnel && isFunnelStepsBreakdownCompareResult(results),
        ],
        stepsWithConversionMetrics: [
            (s) => [s.steps, s.funnelsFilter, s.querySource],
            (
                steps: FunnelStepWithNestedBreakdown[],
                funnelsFilter: FunnelsFilter | null,
                querySource: FunnelsQuery | null
            ): FunnelStepWithConversionMetrics[] => {
                const stepReference = funnelsFilter?.funnelStepReference || FunnelStepReference.total
                // Get optional steps from series (1-indexed)
                const optionalSteps = querySource
                    ? querySource.series
                          .map((_, i: number) => i + 1)
                          .filter((_: number, i: number) => querySource.series[i]?.optionalInFunnel)
                    : []
                return stepsWithConversionMetrics(steps, stepReference, optionalSteps)
            },
        ],

        // hack for experiments to remove displaying baseline from the funnel viz
        disableFunnelBreakdownBaseline: [
            () => [(_, props) => props],
            (props: InsightLogicProps): boolean => !!props.cachedInsight?.disable_baseline,
        ],
        flattenedBreakdowns: [
            (s) => [
                s.stepsWithConversionMetrics,
                s.funnelsFilter,
                s.disableFunnelBreakdownBaseline,
                s.breakdownSorting,
                s.isComparedFunnel,
                s.isBreakdownCompareFunnel,
            ],
            (
                steps: FunnelStepWithConversionMetrics[],
                funnelsFilter: FunnelsFilter | null | undefined,
                disableBaseline: boolean,
                breakdownSorting: string | undefined,
                isComparedFunnel: boolean,
                isBreakdownCompareFunnel: boolean
            ): FlattenedFunnelStepByBreakdown[] => {
                // Pure compare's current/previous bars are not breakdown values — one baseline row
                // per period. Breakdown × compare doubles every row into interleaved period pairs.
                const breakdowns =
                    isComparedFunnel && !isBreakdownCompareFunnel
                        ? flattenedStepsByCompare(steps)
                        : isBreakdownCompareFunnel
                          ? flattenedStepsByBreakdownCompare(steps, funnelsFilter?.layout, disableBaseline)
                          : flattenedStepsByBreakdown(steps, funnelsFilter?.layout, disableBaseline, true)
                if (!breakdownSorting) {
                    return breakdowns
                }

                const isDescending = breakdownSorting.startsWith('-')
                const columnKey = isDescending ? breakdownSorting.slice(1) : breakdownSorting
                const sortOrder = isDescending ? -1 : 1

                return [...breakdowns].sort((a, b) => {
                    return sortOrder * compareBreakdownsByColumnKey(a, b, columnKey)
                })
            },
        ],
        hiddenLegendBreakdowns: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): string[] | undefined =>
                funnelsFilter?.hiddenLegendBreakdowns,
        ],
        breakdownSorting: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): string | undefined => funnelsFilter?.breakdownSorting,
        ],
        resultCustomizations: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined) => funnelsFilter?.resultCustomizations,
        ],
        visibleStepsWithConversionMetrics: [
            (s) => [
                s.stepsWithConversionMetrics,
                s.flattenedBreakdowns,
                s.hiddenLegendBreakdowns,
                s.isComparedFunnel,
                s.isBreakdownCompareFunnel,
            ],
            (
                steps: FunnelStepWithConversionMetrics[],
                flattenedBreakdowns: FlattenedFunnelStepByBreakdown[],
                hiddenLegendBreakdowns: string[] | undefined,
                isComparedFunnel: boolean,
                isBreakdownCompareFunnel: boolean
            ): FunnelStepWithConversionMetrics[] => {
                // Pure compare already shaped nested_breakdown into [current, previous]; skip the
                // breakdown baseline-prepend / hidden-legend reordering, which assumes real breakdowns.
                if (isComparedFunnel && !isBreakdownCompareFunnel) {
                    return steps
                }
                // Count values, not rows — compare doubles rows per period, and a single-value
                // breakdown × compare funnel must not flip into multi-series hidden-legend filtering.
                const isOnlySeries = flattenedBreakdowns.filter((b) => b.compare_label !== 'previous').length <= 1
                // Breakdown + compare: draw the per-period baseline pair (kept in flattenedBreakdowns)
                // as the leading grouped bars — same as the plain-breakdown path below — and shift every
                // real value's color position past the baseline's single slot so the chart bar colors
                // line up with the detailed-results table. Preserve the grouped current/previous pairing
                // and per-value orders (both periods of a value share one order, hence one color).
                if (isBreakdownCompareFunnel) {
                    const baselineRows = flattenedBreakdowns.filter((b) => b.isBaseline)
                    // Offset stays 1 while the baseline is merely hidden, so the remaining values keep
                    // their color positions when the baseline is toggled — same as the plain-breakdown
                    // path, which assigns orders before filtering.
                    const baselineOffset = baselineRows.length > 0 ? 1 : 0
                    // Size each baseline bar by its period's share of the larger period (the larger fills,
                    // the smaller is proportionally shorter) — matching how the value and pure-compare bars
                    // are scaled, so the previous baseline isn't drawn at full height.
                    const compareBasis = Math.max(0, ...baselineRows.map((row) => row.steps?.[0]?.count ?? 0))
                    const visibleBaselineRows = baselineRows.filter(
                        (row) =>
                            isOnlySeries || !hiddenLegendBreakdowns?.includes(getVisibilityKey(row.breakdown_value))
                    )
                    return steps.map((step, stepIndex) => {
                        const baselineEntries = visibleBaselineRows
                            .map((row) => row.steps?.[stepIndex])
                            .filter((s): s is FunnelStepWithConversionMetrics => s != null)
                            .map((s) => ({
                                ...s,
                                order: 0,
                                conversionRates: {
                                    ...s.conversionRates,
                                    fromBasisStep: compareBasis > 0 ? s.count / compareBasis : 0,
                                },
                            }))
                        const valueEntries = (step.nested_breakdown ?? [])
                            .filter(
                                (b) =>
                                    isOnlySeries ||
                                    !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
                            )
                            .map((b) => ({ ...b, order: (b.order ?? 0) + baselineOffset }))
                        return {
                            ...step,
                            nested_breakdown: [...baselineEntries, ...valueEntries],
                        }
                    })
                }
                const baseLineSteps = flattenedBreakdowns.find((b) => b.isBaseline)

                // Build a breakdown order lookup from flattenedBreakdowns (already sorted
                // by breakdownSorting) so the graph matches the table order.
                const breakdownOrder = new Map<string, number>()
                flattenedBreakdowns.forEach((b, i) => breakdownOrder.set(getVisibilityKey(b.breakdown_value), i))

                return steps.map((step, stepIndex) => {
                    const nested = (
                        baseLineSteps?.steps
                            ? [baseLineSteps.steps[stepIndex], ...(step?.nested_breakdown ?? [])]
                            : step?.nested_breakdown
                    )
                        ?.map((b, breakdownIndex) => ({
                            ...b,
                            order: breakdownIndex,
                        }))
                        ?.filter(
                            (b) =>
                                isOnlySeries || !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
                        )
                        ?.sort((a, b) => {
                            const aIdx = breakdownOrder.get(getVisibilityKey(a.breakdown_value)) ?? Infinity
                            const bIdx = breakdownOrder.get(getVisibilityKey(b.breakdown_value)) ?? Infinity
                            return aIdx - bIdx
                        })
                    return {
                        ...step,
                        nested_breakdown: nested,
                    }
                })
            },
        ],

        /*
         * Time-to-convert funnels
         */
        timeConversionResults: [
            (s) => [s.results, s.funnelsFilter],
            (
                results: FunnelResultType,
                funnelsFilter: FunnelsFilter | null | undefined
            ): FunnelsTimeConversionBins | null => {
                if (funnelsFilter?.funnelVizType !== FunnelVizType.TimeToConvert) {
                    return null
                }
                // Compare returns a two-element list tagged with compare_label; take the current period.
                if (Array.isArray(results)) {
                    return (
                        (results as unknown as TimeToConvertCompareBins[]).find(
                            (row) => row.compare_label === 'current'
                        ) ?? null
                    )
                }
                return results as FunnelsTimeConversionBins
            },
        ],
        timeConversionResultsPrevious: [
            (s) => [s.results, s.funnelsFilter],
            (
                results: FunnelResultType,
                funnelsFilter: FunnelsFilter | null | undefined
            ): FunnelsTimeConversionBins | null => {
                if (funnelsFilter?.funnelVizType !== FunnelVizType.TimeToConvert || !Array.isArray(results)) {
                    return null
                }
                return (
                    (results as unknown as TimeToConvertCompareBins[]).find(
                        (row) => row.compare_label === 'previous'
                    ) ?? null
                )
            },
        ],
        histogramGraphData: [
            (s) => [s.timeConversionResults],
            (timeConversionResults: FunnelsTimeConversionBins | null): HistogramGraphDatum[] | null =>
                timeConversionBinsToHistogramData(timeConversionResults),
        ],
        histogramGraphDataPrevious: [
            (s) => [s.timeConversionResultsPrevious],
            (timeConversionResultsPrevious: FunnelsTimeConversionBins | null): HistogramGraphDatum[] | null =>
                timeConversionBinsToHistogramData(timeConversionResultsPrevious),
        ],
        hasFunnelResults: [
            (s) => [s.insightData, s.funnelsFilter, s.steps, s.histogramGraphData, s.querySource, s.stepNames],
            (
                insightData: Record<string, any>,
                funnelsFilter: FunnelsFilter | null | undefined,
                steps: FunnelStepWithNestedBreakdown[],
                histogramGraphData: HistogramGraphDatum[] | null,
                querySource: FunnelsQuery | null,
                stepNames: FunnelStepWithNestedBreakdown[]
            ) => {
                if (!isFunnelsQueryOrLegacyFilter(insightData, querySource)) {
                    return false
                }

                if (funnelsFilter?.funnelVizType === FunnelVizType.Steps || !funnelsFilter?.funnelVizType) {
                    return !!(steps && steps[0] && steps[0].count > -1)
                } else if (funnelsFilter.funnelVizType === FunnelVizType.TimeToConvert) {
                    return (histogramGraphData?.length ?? 0) > 0
                } else if (funnelsFilter.funnelVizType === FunnelVizType.Trends) {
                    return (steps?.length ?? 0) > 0 && !!steps?.[0]?.labels
                } else if (funnelsFilter.funnelVizType === FunnelVizType.Flow && stepNames.length > 0) {
                    return true
                }

                return false
            },
        ],
        numericBinCount: [
            (s) => [s.funnelsFilter, s.timeConversionResults],
            (
                funnelsFilter: FunnelsFilter | null | undefined,
                timeConversionResults: FunnelsTimeConversionBins | null
            ): number => {
                if (funnelsFilter?.binCount === BIN_COUNT_AUTO) {
                    return timeConversionResults?.bins?.length ?? 0
                }
                return funnelsFilter?.binCount ?? 0
            },
        ],

        conversionMetrics: [
            (s) => [s.steps, s.funnelsFilter, s.timeConversionResults, s.insightData],
            (
                steps: FunnelStepWithNestedBreakdown[],
                funnelsFilter: FunnelsFilter | null | undefined,
                timeConversionResults: FunnelsTimeConversionBins | null,
                insightData: Record<string, any>
            ): FunnelTimeConversionMetrics => {
                // steps should be empty in time conversion view. Return metrics precalculated on backend
                if (funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert) {
                    return {
                        medianTime: timeConversionResults?.median_conversion_time ?? null,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                // Handle metrics for trends
                if (funnelsFilter?.funnelVizType === FunnelVizType.Trends) {
                    return {
                        medianTime: null,
                        stepRate: 0,
                        totalRate: average((steps?.[0] as unknown as TrendResult)?.data ?? []) / 100,
                    }
                }

                // Handle metrics for steps
                // no concept of funnel_from_step and funnel_to_step here
                if (steps.length <= 1) {
                    return {
                        medianTime: null,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                const toStep = getLastFilledStep(steps)
                const fromStep = getReferenceStep(steps, FunnelStepReference.total)

                return {
                    // The median of the total funnel time isn't the sum of per-step medians, so it's
                    // computed breakdown-agnostically on the backend and carried as a top-level field.
                    medianTime: (insightData as Partial<FunnelsQueryResponse>).total_median_conversion_time ?? null,
                    stepRate: fromStep.count === 0 ? 0 : toStep.count / fromStep.count,
                    totalRate: steps[0].count === 0 ? 0 : steps[steps.length - 1].count / steps[0].count,
                }
            },
        ],
        conversionWindow: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): Required<FunnelConversionWindow> => {
                const { funnelWindowInterval, funnelWindowIntervalUnit } = funnelsFilter || {}
                return {
                    funnelWindowInterval: funnelWindowInterval || 14,
                    funnelWindowIntervalUnit: funnelWindowIntervalUnit || FunnelConversionWindowTimeUnit.Day,
                }
            },
        ],
        incompletenessOffsetFromEnd: [
            (s) => [s.steps, s.conversionWindow],
            (steps: FunnelStepWithNestedBreakdown[], conversionWindow: Required<FunnelConversionWindow>) => {
                if (steps?.[0]?.days === undefined) {
                    return 0
                }

                // subtract conversion window from today and look for a matching day
                const startDate = getIncompleteConversionWindowStartDate(conversionWindow)
                const startIndex = steps[0].days.findIndex((day) => dayjs(day) >= startDate)

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - steps[0].days.length
                }
                return 0
            },
        ],

        /*
         * Advanced options: funnelOrderType, funnelStepReference, exclusions
         */
        advancedOptionsUsedCount: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): number => {
                let count = 0
                if (funnelsFilter?.funnelOrderType && funnelsFilter?.funnelOrderType !== StepOrderValue.ORDERED) {
                    count = count + 1
                }
                if (
                    funnelsFilter?.funnelStepReference &&
                    funnelsFilter?.funnelStepReference !== FunnelStepReference.total
                ) {
                    count = count + 1
                }
                if (funnelsFilter?.exclusions?.length) {
                    count = count + 1
                }
                return count
            },
        ],

        isSkewed: [
            (s) => [s.conversionMetrics, s.skewWarningHidden],
            (conversionMetrics: FunnelTimeConversionMetrics, skewWarningHidden: boolean): boolean => {
                return !skewWarningHidden && (conversionMetrics.totalRate < 0.1 || conversionMetrics.totalRate > 0.9)
            },
        ],
        indexedSteps: [
            (s) => [s.steps],
            (steps: FunnelStepWithNestedBreakdown[]) => {
                if (!Array.isArray(steps)) {
                    return []
                }
                // Pair rows on `breakdown_value` (no `compare_label`) so current/previous of the
                // same series share the same base color. The downstream color resolver prefers
                // `colorIndex` over `seriesIndex` (see `getTrendResultCustomizationColorToken`),
                // and `LineGraph.processDataset` then dims the previous-period series to 50% alpha.
                const colorIndexMap = new Map<string, number>()
                for (const step of steps) {
                    const key = getFunnelDatasetKey(step)
                    if (!colorIndexMap.has(key)) {
                        colorIndexMap.set(key, colorIndexMap.size)
                    }
                }
                return steps.map((step, index) => {
                    // The funnels runner tags compare rows with `compare_label` but doesn't set
                    // `compare: true`. `LineGraph.processDataset` requires both to dim the previous
                    // line — normalize here so the previous-period series renders at 50% alpha.
                    const stepWithCompare = step as typeof step & {
                        compare_label?: 'current' | 'previous'
                        compare?: boolean
                    }
                    return {
                        ...step,
                        seriesIndex: index,
                        colorIndex: colorIndexMap.get(getFunnelDatasetKey(step)) ?? 0,
                        id: index,
                        compare: stepWithCompare.compare_label != null ? true : stepWithCompare.compare,
                    }
                })
            },
        ],
        getFunnelsColorToken: [
            (s) => [
                s.resultCustomizations,
                s.getTheme,
                s.breakdownFilter,
                s.querySource,
                s.flattenedBreakdowns,
                s.disableFunnelBreakdownBaseline,
            ],
            (
                resultCustomizations:
                    | Record<string, import('~/queries/schema/schema-general').ResultCustomizationByValue>
                    | undefined,
                getTheme: (themeId: number | string | null | undefined) => DataColorTheme | null,
                breakdownFilter: null | import('~/queries/schema/schema-general').BreakdownFilter | undefined,
                querySource: FunnelsQuery | null,
                flattenedBreakdowns: FlattenedFunnelStepByBreakdown[],
                disableFunnelBreakdownBaseline: boolean
            ) => {
                const breakdownPropertyKey = getBreakdownPropertyKey(breakdownFilter)
                // The dashboard's colors live in another logic and are read at call time, so the
                // per-tile fallback map is memoized here on the identity of what it derives from.
                let fallbackSource: { overrides: BreakdownColorConfig[]; theme: DataColorTheme } | null = null
                let fallbackTokens = new Map<number, DataColorToken>()
                const tileFallbackToken = (
                    overrides: BreakdownColorConfig[],
                    theme: DataColorTheme,
                    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
                ): DataColorToken | undefined => {
                    if (fallbackSource?.overrides !== overrides || fallbackSource?.theme !== theme) {
                        fallbackSource = { overrides, theme }
                        // Completion only activates when a dashboard override actually sits on this
                        // tile; a series customization alone must not shift its neighbors' colors.
                        // Once active, customized series claim their slots like overrides do.
                        let hasDashboardOverride = false
                        const series = flattenedBreakdowns.map((breakdown) => {
                            const overrideToken =
                                findBreakdownColorConfig(
                                    overrides,
                                    JSON.parse(getFunnelDatasetKey(breakdown))['breakdown_value'],
                                    breakdownFilter?.breakdown_type,
                                    breakdownPropertyKey
                                )?.colorToken ?? null
                            hasDashboardOverride = hasDashboardOverride || !!overrideToken
                            return {
                                position: getFunnelDatasetPosition(breakdown, disableFunnelBreakdownBaseline),
                                overrideToken:
                                    overrideToken ??
                                    getFunnelResultCustomization(breakdown, resultCustomizations)?.color ??
                                    null,
                            }
                        })
                        fallbackTokens = hasDashboardOverride
                            ? computeTileFallbackTokens(series, Object.keys(theme).length)
                            : new Map<number, DataColorToken>()
                    }
                    return fallbackTokens.get(getFunnelDatasetPosition(dataset, disableFunnelBreakdownBaseline))
                }

                return (
                    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
                ): [DataColorTheme | null, DataColorToken | null] => {
                    const breakdownValue = JSON.parse(getFunnelDatasetKey(dataset))['breakdown_value']

                    // dashboard color overrides
                    const logic = dashboardLogic.findMounted({ id: props.dashboardId })
                    const colorOverride = findBreakdownColorConfig(
                        logic?.values.effectiveBreakdownColors,
                        breakdownValue,
                        breakdownFilter?.breakdown_type,
                        breakdownPropertyKey
                    )

                    if (colorOverride?.colorToken) {
                        // use the dashboard theme, or fallback to the default theme
                        const dashboardTheme = logic?.values.dataColorTheme || getTheme(undefined)
                        return [dashboardTheme, colorOverride.colorToken]
                    }

                    // use the dashboard theme, or fallback to the insight theme, or the default theme
                    const theme = logic?.values.dataColorTheme || getTheme(querySource?.dataColorTheme)
                    if (!theme) {
                        return [null, null]
                    }

                    // On dashboards with auto colors, series without a value override fill the
                    // palette slots the tile's overrides don't use, because the plain
                    // position-based fallback can land on the same slot as an override shown on
                    // this very chart. An explicit per-series customization still wins below.
                    if (logic?.values.autoBreakdownColorsEnabled) {
                        const customizationColor = getFunnelResultCustomization(dataset, resultCustomizations)?.color
                        const fallbackToken = customizationColor
                            ? undefined
                            : tileFallbackToken(logic.values.effectiveBreakdownColors, theme, dataset)
                        if (fallbackToken) {
                            return [theme, fallbackToken]
                        }
                    }

                    return [
                        theme,
                        getFunnelResultCustomizationColorToken(
                            resultCustomizations,
                            theme,
                            dataset,
                            props?.cachedInsight?.disable_baseline
                        ),
                    ]
                }
            },
        ],
        getFunnelsColor: [
            (s) => [s.getFunnelsColorToken],
            (
                getFunnelsColorToken: (
                    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
                ) => [DataColorTheme | null, DataColorToken | null]
            ) => {
                return (dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics) => {
                    const [colorTheme, colorToken] = getFunnelsColorToken(dataset)
                    const color = colorTheme && colorToken ? getColorFromToken(colorTheme, colorToken) : '#000000'
                    // Current/previous compare bars share a color token (no breakdown_value), so the
                    // previous-period bar is dimmed here to distinguish it — same treatment as trends.
                    return (dataset as FunnelStepWithConversionMetrics).compare_label === 'previous'
                        ? dimPreviousPeriodColor(color)
                        : color
                }
            },
        ],
        isStepOptional: [
            (s) => [s.querySource],
            (querySource: FunnelsQuery | null) => {
                return (step: number) => {
                    if (querySource?.kind === NodeKind.FunnelsQuery) {
                        // step is 1-indexed, series is 0-indexed
                        return querySource.series[step - 1]?.optionalInFunnel === true
                    }
                    return false
                }
            },
        ],

        // Validations
        isFunnelWithEnoughSteps: [
            (s) => [s.series],
            (series: import('~/queries/schema/schema-general').FunnelsQuerySeriesNodeUnion[] | null) =>
                isFunnelWithEnoughSteps(series),
        ],
        isFunnelWithIncompleteDataWarehouseStep: [
            (s) => [s.series],
            (series: import('~/queries/schema/schema-general').FunnelsQuerySeriesNodeUnion[] | null) =>
                isFunnelWithIncompleteDataWarehouseStep(series),
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
            (funnelsFilter: FunnelsFilter | null | undefined): FilterType => ({
                events: funnelsFilter?.exclusions?.map(({ funnelFromStep, funnelToStep, ...rest }, index) => ({
                    funnel_from_step: funnelFromStep,
                    funnel_to_step: funnelToStep,
                    order: index,
                    ...seriesNodeToFilter(rest),
                })),
            }),
        ],
    })),

    listeners(({ actions, values }) => ({
        setHiddenLegendBreakdowns: ({ hiddenLegendBreakdowns }) => {
            actions.updateInsightFilter({ hiddenLegendBreakdowns })
        },
        toggleLegendBreakdownVisibility: ({ breakdown }) => {
            values.hiddenLegendBreakdowns?.includes(breakdown)
                ? actions.setHiddenLegendBreakdowns(values.hiddenLegendBreakdowns.filter((b) => b !== breakdown))
                : actions.setHiddenLegendBreakdowns([...(values.hiddenLegendBreakdowns || []), breakdown])
        },
        commitConversionWindow: () => {
            const { conversionWindowInterval, conversionWindowUnit, conversionWindow } = values
            const unit = conversionWindowUnit ?? conversionWindow.funnelWindowIntervalUnit
            const rawInterval = conversionWindowInterval ?? conversionWindow.funnelWindowInterval

            if (!rawInterval) {
                actions.setConversionWindowInterval(conversionWindow.funnelWindowInterval)
                return
            }

            const [min, max] = TIME_INTERVAL_BOUNDS[unit]
            const interval = Math.min(Math.max(rawInterval, min), max)

            if (interval !== rawInterval) {
                actions.setConversionWindowInterval(interval)
            }

            if (
                interval !== conversionWindow.funnelWindowInterval ||
                unit !== conversionWindow.funnelWindowIntervalUnit
            ) {
                actions.updateInsightFilter({
                    funnelWindowInterval: interval,
                    funnelWindowIntervalUnit: unit,
                })
            }
        },
        setBreakdownSorting: ({ breakdownSorting }) => {
            // updateInsightFilter debounces 300ms, too slow for the table's controlled sort indicator
            const update: Partial<FunnelsQuery> = {
                funnelsFilter: { ...values.funnelsFilter, breakdownSorting },
            }
            actions.updateQuerySource(update)
        },
    })),
])
