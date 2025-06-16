import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { match } from 'ts-pattern'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import type {
    ActionsNode,
    BreakdownFilter,
    DateRange,
    EventsNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetric,
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
const getDefaultDateRange = (): DateRange => ({
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
const getMathProperties = (
    source: ExperimentMetricSource
): { math: ExperimentMetricMathType; math_property?: string } =>
    match(source)
        .with({ math: ExperimentMetricMathType.Sum }, ({ math, math_property }) => ({
            math,
            math_property,
        }))
        .with({ math: ExperimentMetricMathType.UniqueSessions }, ({ math }) => ({ math }))
        .otherwise(() => ({ math: ExperimentMetricMathType.TotalCount, math_property: undefined }))

type MetricToQueryOptions = {
    breakdownFilter: BreakdownFilter
    filterTestAccounts: boolean
    trendsFilter: TrendsFilter
    trendsInterval: IntervalType
    funnelsFilter: FunnelsFilter
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
    (options?: Partial<MetricToQueryOptions>) =>
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
                    series: getFunnelSeries(funnelMetric),
                }) as FunnelsQuery
            })
            .otherwise(() => undefined)
    }

/**
 * takes an experiment funnel metric and returns a series of events and actions
 * that can be used in a query.
 */
const getFunnelSeries = (funnelMetric: ExperimentFunnelMetric): (EventsNode | ActionsNode)[] => {
    const { events, actions } = getFilter(funnelMetric)

    return actionsAndEventsToSeries(
        {
            actions,
            events,
            data_warehouse: [],
        } as any,
        true,
        MathAvailability.None
    ).filter((series) => series.kind === NodeKind.EventsNode || series.kind === NodeKind.ActionsNode) as (
        | EventsNode
        | ActionsNode
    )[]
}

/**
 * takes an experiment funnel step and returns a source node that can be used in a query
 */
const createSourceNode = (step: ExperimentFunnelMetricStep): ExperimentMetricSource => {
    return {
        kind: step.kind,
        type: step.kind === NodeKind.EventsNode ? 'events' : 'actions',
        id: step.kind === NodeKind.EventsNode ? step.event : step.id,
        name: step.kind === NodeKind.EventsNode ? step.event : step.name,
        math: step.math,
        math_property: step.math_property,
        math_hogql: step.math_hogql,
        properties: step.properties,
        /**
         * TODO: datawarehouse is not supported yet.
         * See ExperimentFunnelMetricStep type definition.
         */
        // ...(step.kind === NodeKind.DataWarehouseNode && {
        //     timestamp_field: step.timestamp_field,
        //     events_join_key: step.events_join_key,
        //     data_warehouse_join_key: step.data_warehouse_join_key,
        // }),
    } as ExperimentMetricSource
}

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
                /**
                 * TODO: datawarehouse is not supported yet.
                 * See ExperimentFunnelMetricStep type definition.
                 */
                // } else if (source.kind === NodeKind.DataWarehouseNode) {
                //     return {
                //         events: [],
                //         actions: [],
                //         data_warehouse: [createSourceNode(source)],
                //     }
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
                data_warehouse: [],
            }
        })
        .otherwise(() => ({
            events: [],
            actions: [],
            data_warehouse: [],
        }))
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

export const addExposureToMetric =
    (exposureEvent: EventsNode) =>
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
    (options: Partial<InsightVizNodeOptions>) =>
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
