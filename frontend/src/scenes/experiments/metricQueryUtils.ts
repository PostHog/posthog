import { match } from 'ts-pattern'

import { EXPERIMENT_DEFAULT_DURATION, FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isNotNil } from 'lib/utils/guards'
import { objectCleanWithEmpty } from 'lib/utils/objects'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { cleanSeriesNodes } from 'scenes/insights/filters/ActionFilter/cleanSeriesNodes'
import {
    SeriesNode,
    isActionsSeriesNode,
    isEventsSeriesNode,
    isWarehouseSeriesNode,
} from 'scenes/insights/filters/ActionFilter/seriesNode'

import type {
    ActionsNode,
    BreakdownFilter,
    DataWarehouseNode,
    DateRange,
    EntityNode,
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentMetric,
    ExperimentMetricSource,
    ExperimentMetricTypeProps,
    ExperimentWarehouseNativeNode,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
    InsightVizNode,
    RefreshType,
    TrendsFilter,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { ExperimentMetricType, ExperimentWarehouseNativeMathType, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import type { IntervalType } from '~/types'
import { ChartDisplayType, ExperimentMetricMathType } from '~/types'

/**
 * We extract all the math properties from the EntityNode type so we can use them as
 * options when creating a query. Tools like the running time calculator have to set
 * math properties for specific elements in the query.
 */
type MathProperties = {
    [K in keyof EntityNode as K extends `math${string}` ? K : never]: EntityNode[K]
}

/**
 * we need a left to right compose function. We won't use right to left
 * because it's counter intuitive for people not familiar with functional programming...
 *
 * this should be extracted into a library...
 */
export function compose<A, B, C>(f1: (a: A) => B, f2: (b: B) => C): (a: A) => C
export function compose<A, B, C, D>(f1: (a: A) => B, f2: (b: B) => C, f3: (c: C) => D): (a: A) => D
export function compose(...fns: Array<(arg: any) => any>): (arg: any) => any {
    return (arg: any) => fns.reduce((acc, fn) => fn(acc), arg)
}

const isEventMetricSource = (source: ExperimentMetricSource): source is EventsNode =>
    source.kind === NodeKind.EventsNode

/**
 * Converts ExperimentMetricSource to the appropriate query node type
 */
const convertSourceToQueryNode = (source: ExperimentMetricSource): EventsNode | ActionsNode | DataWarehouseNode => {
    return match(source)
        .with(
            { kind: NodeKind.EventsNode },
            (event): EventsNode => ({
                kind: NodeKind.EventsNode,
                event: event.event,
                name: event.name,
                properties: event.properties,
            })
        )
        .with(
            { kind: NodeKind.ActionsNode },
            (action): ActionsNode => ({
                kind: NodeKind.ActionsNode,
                id: action.id,
                name: action.name,
                properties: action.properties,
            })
        )
        .with(
            { kind: NodeKind.ExperimentDataWarehouseNode },
            (dataWarehouse): DataWarehouseNode => ({
                kind: NodeKind.DataWarehouseNode,
                id: dataWarehouse.table_name,
                name: dataWarehouse.name,
                table_name: dataWarehouse.table_name,
                timestamp_field: dataWarehouse.timestamp_field,
                distinct_id_field: dataWarehouse.events_join_key,
                id_field: dataWarehouse.data_warehouse_join_key,
            })
        )
        .with({ kind: NodeKind.ExperimentWarehouseNativeNode }, () => {
            throw new Error('Warehouse-native sources cannot be shown as an insight yet')
        })
        .exhaustive()
}

const defaultTrendsFilter: TrendsFilter = {
    display: ChartDisplayType.ActionsLineGraph,
}

const defaultFunnelsFilter: FunnelsFilter = {
    layout: FunnelLayout.horizontal,
}

/**
 * returns the default date range
 */
const getDefaultDateRange = (): DateRange => ({
    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
    explicitDate: true,
})

/**
 * returns the math properties for the source
 */
export const getMathProperties = (source: ExperimentMetricSource): MathProperties => {
    if (source.kind === NodeKind.ExperimentWarehouseNativeNode) {
        return source.math === ExperimentWarehouseNativeMathType.Sum
            ? { math: ExperimentMetricMathType.Sum, math_property: source.math_property }
            : { math: ExperimentMetricMathType.TotalCount, math_property: undefined }
    }
    if (!source.math || source.math === ExperimentMetricMathType.TotalCount) {
        return { math: ExperimentMetricMathType.TotalCount, math_property: undefined }
    }

    if (source.math === ExperimentMetricMathType.UniqueSessions) {
        return { math: source.math }
    }

    // For Sum, Avg, Min, Max - all require math_property
    return { math: source.math, math_property: source.math_property }
}

type GetQueryOptions = {
    breakdownFilter: BreakdownFilter
    filterTestAccounts: boolean
    trendsFilter: TrendsFilter
    trendsInterval: IntervalType
    funnelsFilter: FunnelsFilter
    funnelsInterval: IntervalType
    dateRange: DateRange
}

/**
 * Returns a complete FunnelQuery | TrendsQuery with strong defaults for the
 * provided ExperimentMetric.
 *
 * This query can be used on Insights like:
 * - Metric Preview
 * - Results Breakdowns
 */
export const getQuery =
    (options?: Partial<GetQueryOptions>) =>
    (metric: ExperimentMetric): FunnelsQuery | TrendsQuery | undefined => {
        /**
         * we get all the options or their defaults. There's no overrides that could
         * cause unexpected effects.
         */
        const {
            breakdownFilter = {},
            filterTestAccounts = true,
            trendsFilter = defaultTrendsFilter,
            trendsInterval = 'day',
            funnelsFilter = defaultFunnelsFilter,
            funnelsInterval = 'day',
            dateRange = getDefaultDateRange(),
        } = options || {}

        return match(metric)
            .with({ metric_type: ExperimentMetricType.MEAN }, (meanMetric) => {
                const source = meanMetric.source

                // Return undefined if this is not an EventsNode and has no math specified
                if (!isEventMetricSource(source) && !source.math) {
                    return undefined
                }

                /**
                 * return a TrendsQuery
                 */
                return setLatestVersionsOnQuery({
                    kind: NodeKind.TrendsQuery,
                    filterTestAccounts,
                    dateRange,
                    interval: trendsInterval,
                    trendsFilter,
                    series: [
                        {
                            ...convertSourceToQueryNode(source),
                            ...getMathProperties(source),
                        },
                    ],
                }) as TrendsQuery
            })
            .with({ metric_type: ExperimentMetricType.FUNNEL }, (funnelMetric) => {
                /**
                 * return a FunnelsQuery
                 */
                return setLatestVersionsOnQuery({
                    kind: NodeKind.FunnelsQuery,
                    filterTestAccounts,
                    // only add breakdownFilter if it's not empty. It has no default value.
                    ...(Object.keys(breakdownFilter).length > 0 ? { breakdownFilter } : {}),
                    dateRange,
                    funnelsFilter,
                    interval: funnelsInterval,
                    series: getFunnelSeries(funnelMetric),
                }) as FunnelsQuery
            })
            .otherwise(() => undefined)
    }

/** Funnel steps carry no math, so only identity, name and properties cross over. */
const getFunnelSeries = (
    funnelMetric: ExperimentFunnelMetric
): (EventsNode | ActionsNode | FunnelsDataWarehouseNode)[] =>
    funnelMetric.series.map((step) =>
        match(step)
            .with({ kind: NodeKind.EventsNode }, (eventStep) =>
                objectCleanWithEmpty({
                    kind: NodeKind.EventsNode as const,
                    event: eventStep.event,
                    name: eventStep.name || eventStep.event || undefined,
                    custom_name: eventStep.custom_name,
                    properties: eventStep.properties,
                })
            )
            .with({ kind: NodeKind.ActionsNode }, (actionStep) =>
                objectCleanWithEmpty({
                    kind: NodeKind.ActionsNode as const,
                    id: actionStep.id,
                    name: actionStep.name || undefined,
                    custom_name: actionStep.custom_name,
                    properties: actionStep.properties,
                })
            )
            .with({ kind: NodeKind.ExperimentDataWarehouseNode }, (dwStep) =>
                objectCleanWithEmpty({
                    kind: NodeKind.FunnelsDataWarehouseNode as const,
                    id: dwStep.table_name,
                    name: dwStep.name || dwStep.table_name,
                    custom_name: dwStep.custom_name,
                    table_name: dwStep.table_name,
                    timestamp_field: dwStep.timestamp_field,
                    id_field: dwStep.data_warehouse_join_key,
                    aggregation_target_field: dwStep.events_join_key,
                    properties: dwStep.properties,
                })
            )
            .exhaustive()
    )

/**
 * The series editor has rows for events, actions and synced warehouse tables only. A
 * warehouse-native source has no row yet, so the form refuses it like the insight converters do.
 */
export function metricSourcesToSeries(sources: ExperimentMetricSource[]): SeriesNode[] {
    return sources.map((source) => {
        if (source.kind === NodeKind.ExperimentWarehouseNativeNode) {
            throw new Error('Warehouse-native sources cannot be edited in the metric form yet')
        }
        return source
    })
}

/**
 * The picker mirrors a warehouse table's name onto `id`, which `ExperimentDataWarehouseNode` does
 * not accept, so a table keeps only `table_name`. A group has no experiment equivalent and gives null.
 */
/** The sources the series picker can produce. A warehouse-native source has no picker row. */
type PickedMetricSource = Exclude<ExperimentMetricSource, ExperimentWarehouseNativeNode>

const toExperimentSourceNode = (node: SeriesNode): PickedMetricSource | null => {
    if (isEventsSeriesNode(node) || isActionsSeriesNode(node)) {
        return node
    }
    if (isWarehouseSeriesNode(node)) {
        const { id: _id, ...warehouseNode } = node as SeriesNode & { id?: string }
        return { ...warehouseNode, kind: NodeKind.ExperimentDataWarehouseNode } as PickedMetricSource
    }
    return null
}

/**
 * Turns the series a single-source picker emits into a metric source, with total count as the
 * default math. Returns null when the picker holds no event, action or table.
 */
export function seriesToMetricSource(series: SeriesNode[]): PickedMetricSource | null {
    const [node] = cleanSeriesNodes(series.slice(0, 1), MathAvailability.All)
    const source = node ? toExperimentSourceNode(node) : null
    if (source?.kind === NodeKind.EventsNode) {
        // Fall back to `name` when taxonomic selection leaves `event` empty/null.
        return { ...source, event: source.event || source.name }
    }
    return source
}

/**
 * Turns the series the metric picker emits into the part of the metric it edits: the funnel
 * steps, which carry no math, or the mean metric's source.
 */
export function seriesToMetricConfig(
    metricType: ExperimentMetricType,
    series: SeriesNode[]
): ExperimentMetricTypeProps | undefined {
    return match(metricType)
        .with(ExperimentMetricType.FUNNEL, () => {
            const steps = cleanSeriesNodes(series, MathAvailability.None).map(toExperimentSourceNode).filter(isNotNil)
            return steps.length > 0 ? { metric_type: ExperimentMetricType.FUNNEL as const, series: steps } : undefined
        })
        .with(ExperimentMetricType.MEAN, () => {
            const source = seriesToMetricSource(series)
            return source ? { metric_type: ExperimentMetricType.MEAN as const, source } : undefined
        })
        .otherwise(() => undefined)
}

/**
 * we can only add exposure to funnel metrics, that have a series.
 * we may want to add exposure at this stage to process all items in the series
 * together, or make sense sematically
 */
export const addExposureToMetric =
    (exposureEvent: EventsNode | ActionsNode) =>
    (metric: ExperimentMetric): ExperimentMetric =>
        match(metric)
            .with({ metric_type: ExperimentMetricType.FUNNEL }, (funnelMetric) => {
                /**
                 * we add the exposure event node to the funnel metric
                 */
                return {
                    ...funnelMetric,
                    series: [exposureEvent, ...funnelMetric.series],
                }
            })
            .otherwise(() => metric)

type InsightVizNodeOptions = {
    showTable: boolean
    showLastComputation: boolean
    showLastComputationRefresh: boolean
}

/**
 * wraps a query into an InsightVizNode, by adding some default options.
 * this is the format that the Query component expects
 */
export const getInsight =
    (options?: Partial<InsightVizNodeOptions>) =>
    (query: FunnelsQuery | TrendsQuery | undefined): InsightVizNode | undefined => {
        if (!query) {
            return undefined
        }

        const { showTable = false, showLastComputation = false, showLastComputationRefresh = false } = options || {}
        return {
            kind: NodeKind.InsightVizNode,
            source: query,
            showTable,
            showLastComputation,
            showLastComputationRefresh,
        }
    }

// Gated by the experiments-sync-queries flag during rollout. Flag on → run experiment
// queries synchronously in the web request; flag off → legacy Celery/async path.
// Once the flag reaches 100%, inline the sync branch and delete these helpers.
export const getExperimentExecutionMode = (featureFlags: FeatureFlagsSet): 'sync' | 'async' =>
    featureFlags[FEATURE_FLAGS.EXPERIMENTS_SYNC_QUERIES] ? 'sync' : 'async'

export const getExperimentRefreshMode = (featureFlags: FeatureFlagsSet, forceRefresh: boolean): RefreshType => {
    if (getExperimentExecutionMode(featureFlags) === 'sync') {
        return forceRefresh ? 'force_blocking' : 'blocking'
    }
    return forceRefresh ? 'force_async' : 'async'
}
