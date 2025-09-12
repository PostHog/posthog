import { match } from 'ts-pattern'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import {
    FilterTypeActionsAndEvents,
    actionsAndEventsToSeries,
} from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import type {
    ActionsNode,
    BreakdownFilter,
    DataWarehouseNode,
    DateRange,
    EntityNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetric,
    ExperimentFunnelMetricStep,
    ExperimentMetric,
    ExperimentMetricTypeProps,
    FunnelsFilter,
    FunnelsQuery,
    InsightVizNode,
    TrendsFilter,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { ExperimentMetricSource, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import type { Experiment, FilterType, IntervalType, MultivariateFlagVariant } from '~/types'
import { ChartDisplayType, ExperimentMetricMathType, PropertyFilterType, PropertyOperator } from '~/types'

// TODO: extract types to a separate file, since this is a circular dependency
import type { EventConfig } from './RunningTimeCalculator/runningTimeCalculatorLogic'

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
export const getDefaultDateRange = (): DateRange => ({
    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
    explicitDate: true,
})

/**
 * returns a date range using an experiment's start and end date, or the default duration if not set.
 */
export const getExperimentDateRange = (experiment: Experiment): DateRange => {
    const defaultRange = getDefaultDateRange()
    return {
        date_from: experiment.start_date ?? defaultRange.date_from,
        date_to: experiment.end_date ?? defaultRange.date_to,
        explicitDate: true,
    }
}

/**
 * returns the math properties for the source
 */
export const getMathProperties = (source: ExperimentMetricSource): MathProperties => {
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
                    series: getFunnelSeries(funnelMetric), // Use proper conversion pipeline
                }) as FunnelsQuery
            })
            .otherwise(() => undefined)
    }

/**
 * converts a funnel metric to a series of events and actions
 * this is part of the conversion pipeline for funnel metrics.
 *
 * Funnel series are validated with:
 * Metric Series -> Filter -> Query Series
 */
const getFunnelSeries = (funnelMetric: ExperimentFunnelMetric): (EventsNode | ActionsNode)[] => {
    const { events, actions } = getFilter(funnelMetric)

    return actionsAndEventsToSeries(
        {
            actions,
            events,
            data_warehouse: [], // Data warehouse not supported in funnels
        } as FilterTypeActionsAndEvents,
        true, // includeProperties
        MathAvailability.None // No math for funnels
    ).filter((series) => series.kind === NodeKind.EventsNode || series.kind === NodeKind.ActionsNode) as (
        | EventsNode
        | ActionsNode
    )[]
}

/**
 * Creates an empty filter structure
 */
const createEmptyFilter = (): FilterType => ({
    events: [],
    actions: [],
    data_warehouse: [],
})

/**
 * Helper function to create a filter from a single source
 */
export const createFilterForSource = (source: ExperimentMetricSource): FilterType => {
    return match(source)
        .with({ kind: NodeKind.EventsNode }, (eventSource) => ({
            events: [createSourceNode(eventSource)],
            actions: [],
            data_warehouse: [],
        }))
        .with({ kind: NodeKind.ActionsNode }, (actionSource) => ({
            events: [],
            actions: [createSourceNode(actionSource)],
            data_warehouse: [],
        }))
        .with({ kind: NodeKind.ExperimentDataWarehouseNode }, (dwSource) => ({
            events: [],
            actions: [],
            data_warehouse: [createSourceNode(dwSource)],
        }))
        .otherwise(() => createEmptyFilter())
}

/**
 * takes a metric and returns a filter that can be used as part of a query.
 */
export const getFilter = (metric: ExperimentMetric): FilterType => {
    return match(metric)
        .with({ metric_type: ExperimentMetricType.MEAN }, (meanMetric) => createFilterForSource(meanMetric.source))
        .with({ metric_type: ExperimentMetricType.FUNNEL }, (funnelMetric) => {
            /**
             * we create a source node for each step on the funnel series.
             */
            const funnelSteps = funnelMetric.series.map((step, index) => {
                return {
                    ...createSourceNode(step),
                    order: index,
                    type: step.kind === NodeKind.EventsNode ? 'events' : 'actions',
                }
            })

            return {
                events: funnelSteps.filter((step) => step.type === 'events'),
                actions: funnelSteps.filter((step) => step.type === 'actions'),
                data_warehouse: [], // datawarehouse nodes are not supported for funnel metrics yet
            }
        })
        .with({ metric_type: ExperimentMetricType.RATIO }, (ratioMetric) => {
            // For ratio metrics, we need to combine numerator and denominator filters
            const numeratorFilter = createFilterForSource(ratioMetric.numerator)
            const denominatorFilter = createFilterForSource(ratioMetric.denominator)

            return {
                events: [...(numeratorFilter.events || []), ...(denominatorFilter.events || [])],
                actions: [...(numeratorFilter.actions || []), ...(denominatorFilter.actions || [])],
                data_warehouse: [
                    ...(numeratorFilter.data_warehouse || []),
                    ...(denominatorFilter.data_warehouse || []),
                ],
            }
        })
        .otherwise(() => createEmptyFilter())
}

/**
 * Enhanced version of ExperimentMetricSource with legacy filter properties
 * This type represents what createSourceNode actually returns - a node with additional
 * filter-compatible properties needed for the legacy filter system
 */
type ExperimentMetricSourceWithType =
    | (EventsNode & { type: 'events'; id: string; name: string })
    | (ActionsNode & { type: 'actions'; id: number; name: string })
    | (ExperimentDataWarehouseNode & { type: 'data_warehouse'; id: string; name: string })

/**
 * Converts filter data to a metric source (EventsNode, ActionsNode, or ExperimentDataWarehouseNode)
 * Used for ratio metrics and mean metrics to support all source types
 */
export function filterToMetricSource(
    actions: Record<string, any>[] | undefined,
    events: Record<string, any>[] | undefined,
    data_warehouse: Record<string, any>[] | undefined
): ExperimentMetricSource | null {
    if (events?.[0]) {
        return {
            kind: NodeKind.EventsNode,
            event: events[0].id,
            name: events[0].name,
            math: events[0].math || ExperimentMetricMathType.TotalCount,
            math_property: events[0].math_property,
            math_hogql: events[0].math_hogql,
            math_group_type_index: events[0].math_group_type_index,
            properties: events[0].properties,
        }
    }

    if (actions?.[0]) {
        return {
            kind: NodeKind.ActionsNode,
            id: actions[0].id,
            name: actions[0].name,
            math: actions[0].math || ExperimentMetricMathType.TotalCount,
            math_property: actions[0].math_property,
            math_hogql: actions[0].math_hogql,
            math_group_type_index: actions[0].math_group_type_index,
            properties: actions[0].properties,
        }
    }

    if (data_warehouse?.[0]) {
        return {
            kind: NodeKind.ExperimentDataWarehouseNode,
            name: data_warehouse[0].name,
            table_name: data_warehouse[0].id,
            timestamp_field: data_warehouse[0].timestamp_field,
            events_join_key: data_warehouse[0].events_join_key,
            data_warehouse_join_key: data_warehouse[0].data_warehouse_join_key,
            math: data_warehouse[0].math || ExperimentMetricMathType.TotalCount,
            math_property: data_warehouse[0].math_property,
            math_hogql: data_warehouse[0].math_hogql,
            math_group_type_index: data_warehouse[0].math_group_type_index,
            properties: data_warehouse[0].properties,
        }
    }

    return null
}

/**
 * Converts filter format to metric configuration
 * This is the reverse operation of getFilter
 */
export function filterToMetricConfig(
    metricType: ExperimentMetricType,
    actions: Record<string, any>[] | undefined,
    events: Record<string, any>[] | undefined,
    data_warehouse: Record<string, any>[] | undefined
): ExperimentMetricTypeProps | undefined {
    return match(metricType)
        .with(ExperimentMetricType.FUNNEL, () => {
            // Combine events and actions and sort by order
            const eventSteps =
                events?.map(
                    (event) =>
                        ({
                            kind: NodeKind.EventsNode,
                            event: event.id,
                            custom_name: event.custom_name,
                            properties: event.properties,
                            order: event.order,
                        }) as EventsNode & { order: number }
                ) || []

            const actionSteps =
                actions?.map(
                    (action) =>
                        ({
                            kind: NodeKind.ActionsNode,
                            id: action.id,
                            name: action.name,
                            properties: action.properties,
                            order: action.order,
                        }) as ActionsNode & { order: number }
                ) || []

            const combinedSteps = [...eventSteps, ...actionSteps].sort((a, b) => a.order - b.order)

            // Remove the temporary order field
            const series = combinedSteps.map(({ order, ...step }) => step as ExperimentFunnelMetricStep)

            return series.length > 0
                ? {
                      metric_type: ExperimentMetricType.FUNNEL as const,
                      series,
                  }
                : undefined
        })
        .with(ExperimentMetricType.MEAN, () => {
            const source = filterToMetricSource(actions, events, data_warehouse)
            return source
                ? {
                      metric_type: ExperimentMetricType.MEAN as const,
                      source,
                  }
                : undefined
        })
        .otherwise(() => undefined)
}

/**
 * this is a type adapter between metrics and filters.
 * takes an experiment mean metric source or funnel metric step and returns a source node that can be used in a filter
 */
const createSourceNode = (step: ExperimentFunnelMetricStep | ExperimentMetricSource): ExperimentMetricSourceWithType =>
    match(step)
        .with({ kind: NodeKind.EventsNode }, (eventStep) => ({
            ...eventStep,
            type: 'events' as const,
            id: eventStep.event || '',
            name: eventStep.name || eventStep.event || '',
        }))
        .with({ kind: NodeKind.ActionsNode }, (actionStep) => ({
            ...actionStep,
            type: 'actions' as const,
            id: actionStep.id,
            name: actionStep.name || '',
        }))
        .with({ kind: NodeKind.ExperimentDataWarehouseNode }, (dwStep) => ({
            ...dwStep,
            type: 'data_warehouse' as const,
            id: dwStep.table_name,
            name: dwStep.name || dwStep.table_name,
        }))
        .exhaustive()

/**
 * this is used on the running time calculator to create a node that can be used in a filter
 */
export const getEventNode = (
    event: EventConfig,
    options?: { mathProps?: MathProperties }
): EventsNode | ActionsNode => {
    return match(event)
        .with({ entityType: TaxonomicFilterGroupType.Events }, (event) => {
            return {
                kind: NodeKind.EventsNode as const,
                name: event.name,
                event: event.event,
                properties: event.properties,
                ...options?.mathProps,
            }
        })
        .with({ entityType: TaxonomicFilterGroupType.Actions }, (action) => {
            return {
                kind: NodeKind.ActionsNode as const,
                id: parseInt(action.event, 10) || 0,
                name: action.name,
                properties: action.properties,
                ...options?.mathProps,
            }
        })
        .exhaustive()
}

/**
 * converts the experiment exposure config in to an events node
 */
export const getExposureConfigEventsNode = (
    exposureConfig: ExperimentEventExposureConfig,
    options: { featureFlagKey: string; featureFlagVariants: MultivariateFlagVariant[] }
): EventsNode => {
    const exposure_step_name = 'Experiment exposure'
    if (exposureConfig && exposureConfig.event !== '$feature_flag_called') {
        const { featureFlagKey, featureFlagVariants } = options
        return {
            kind: NodeKind.EventsNode,
            custom_name: exposure_step_name,
            event: exposureConfig.event,
            properties: [
                ...(exposureConfig.properties || []),
                {
                    key: `$feature/${featureFlagKey}`,
                    type: PropertyFilterType.Event,
                    value: featureFlagVariants.map(({ key }) => key),
                    operator: PropertyOperator.Exact,
                },
            ],
        }
    }

    return {
        kind: NodeKind.EventsNode,
        custom_name: exposure_step_name,
        event: '$feature_flag_called',
        properties: [
            {
                key: '$feature_flag',
                type: PropertyFilterType.Event,
                value: options.featureFlagKey,
                operator: PropertyOperator.Exact,
            },
        ],
    }
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

/**
 * unlike metrics, both Funnels and Trends queries have a series property,
 * so we can add the exposure event to the series.
 */
export const addExposureToQuery =
    (exposureEvent: EventsNode | ActionsNode) =>
    (query: FunnelsQuery | TrendsQuery | undefined): FunnelsQuery | TrendsQuery | undefined =>
        query
            ? {
                  ...query,
                  series: [exposureEvent, ...query.series],
              }
            : undefined

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
