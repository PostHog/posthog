import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { match } from 'ts-pattern'
import type {
    ActionsNode,
    BreakdownFilter,
    DateRange,
    EntityNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetricStep,
    ExperimentMetric,
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
export const getMathProperties = (source: ExperimentMetricSource): MathProperties =>
    match(source)
        .with({ math: ExperimentMetricMathType.Sum }, ({ math, math_property }) => ({
            math,
            math_property,
        }))
        .with({ math: ExperimentMetricMathType.UniqueSessions }, ({ math }) => ({ math }))
        .otherwise(() => ({ math: ExperimentMetricMathType.TotalCount, math_property: undefined }))

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
                            kind: source.kind,
                            ...match(source)
                                .with({ kind: NodeKind.EventsNode }, (event) => ({
                                    event: event.event,
                                    name: event.name,
                                }))
                                .with({ kind: NodeKind.ActionsNode }, (action) => ({
                                    id: action.id,
                                    name: action.name,
                                }))
                                .with({ kind: NodeKind.ExperimentDataWarehouseNode }, (dataWarehouse) => ({
                                    table_name: dataWarehouse.table_name,
                                    timestamp_field: dataWarehouse.timestamp_field,
                                    events_join_key: dataWarehouse.events_join_key,
                                    data_warehouse_join_key: dataWarehouse.data_warehouse_join_key,
                                    name: dataWarehouse.name,
                                }))
                                .otherwise(() => {}),
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
                    series: funnelMetric.series,
                }) as FunnelsQuery
            })
            .otherwise(() => undefined)
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
 * takes a metric and returns a filter that can be used as part of a query.
 */
export const getFilter = (metric: ExperimentMetric): FilterType => {
    return match(metric)
        .with({ metric_type: ExperimentMetricType.MEAN }, (meanMetric) => {
            const source = meanMetric.source

            if (source.kind === NodeKind.EventsNode) {
                return {
                    events: [createSourceNode(source)],
                    actions: [],
                    data_warehouse: [],
                }
            } else if (source.kind === NodeKind.ActionsNode) {
                return {
                    events: [],
                    actions: [createSourceNode(source)],
                    data_warehouse: [],
                }
            } else if (source.kind === NodeKind.ExperimentDataWarehouseNode) {
                return {
                    events: [],
                    actions: [],
                    data_warehouse: [createSourceNode(source)],
                }
            }

            return {
                events: [],
                actions: [],
                data_warehouse: [],
            }
        })
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
        .otherwise(() => ({
            events: [],
            actions: [],
            data_warehouse: [],
        }))
}

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

export const getExposureConfigEventsNode = (
    exposureConfig: ExperimentEventExposureConfig,
    options: { featureFlagKey: string; featureFlagVariants: MultivariateFlagVariant[] }
): EventsNode => {
    if (exposureConfig && exposureConfig.event !== '$feature_flag_called') {
        const { featureFlagKey, featureFlagVariants } = options
        return {
            kind: NodeKind.EventsNode,
            custom_name: exposureConfig.event,
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
        custom_name: '$feature_flag_called',
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
