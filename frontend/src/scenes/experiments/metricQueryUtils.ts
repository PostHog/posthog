import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { match } from 'ts-pattern'
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
} from '~/queries/schema'
import { ExperimentMetricSource, ExperimentMetricType, NodeKind } from '~/queries/schema'
import type { Experiment, FilterType, IntervalType, MultivariateFlagVariant } from '~/types'
import { ChartDisplayType, ExperimentMetricMathType, PropertyFilterType, PropertyOperator } from '~/types'

import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'

const isEventMetricSource = (source: ExperimentMetricSource): source is EventsNode =>
    source.kind === NodeKind.EventsNode

const isActionMericSorce = (source: ExperimentMetricSource): source is ActionsNode =>
    source.kind === NodeKind.ActionsNode

const defaultTrendsFilter: TrendsFilter = {
    display: ChartDisplayType.ActionsLineGraph,
}

const defaultFunnelsFilter: FunnelsFilter = {
    layout: FunnelLayout.horizontal,
}

/**
 * returns the default date range
 */
const getDefultDateRange = (): DateRange => ({
    date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
    date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
    explicitDate: true,
})

/**
 * returns a date range using an experiment's start and end date, or the default duration if not set.
 */
export const getExperimentDateRange = (experiment: Experiment): DateRange => {
    const defaultRange = getDefultDateRange()
    return {
        date_from: experiment.start_date ?? defaultRange.date_from,
        date_to: experiment.end_date ?? defaultRange.date_to,
        explicitDate: true,
    }
}

/**
 * returns the math properties for the source
 */
const getMathProperties = (source: ExperimentMetricSource) =>
    match(source)
        .with({ math: ExperimentMetricMathType.Sum }, ({ math, math_property }) => ({
            math,
            math_property,
        }))
        .with({ math: ExperimentMetricMathType.UniqueSessions }, ({ math }) => ({ math }))
        .otherwise(() => {})

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
export function metricToQuery(
    metric: ExperimentMetric,
    options?: Partial<MetricToQueryOptions>
): FunnelsQuery | TrendsQuery | undefined {
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
        dateRange = getDefultDateRange(),
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
            return {
                kind: NodeKind.TrendsQuery,
                filterTestAccounts,
                dateRange,
                interval: trendsInterval,
                trendsFilter,
                series: [
                    {
                        kind: source.kind,
                        ...match(source)
                            .with({ kind: NodeKind.EventsNode }, (event) => ({ event: event.event, name: event.name }))
                            .with({ kind: NodeKind.ActionsNode }, (action) => ({ id: action.id, name: action.name }))
                            .otherwise(() => {}),
                        ...getMathProperties(source),
                    },
                ],
            } as TrendsQuery
        })
        .with({ metric_type: ExperimentMetricType.FUNNEL }, (funnelMetric) => {
            /**
             * return a FunnelsQuery
             */
            return {
                kind: NodeKind.FunnelsQuery,
                filterTestAccounts,
                // only add breakdownFilter if it's not empty. It has no default value.
                ...(Object.keys(breakdownFilter).length > 0 ? { breakdownFilter } : {}),
                dateRange,
                funnelsFilter,
                // series: getFunnelPreviewSeries(funnelMetric),
                series: getFunnelSeries(funnelMetric),
            } as FunnelsQuery
        })
        .otherwise(() => undefined)
}

/**
 * takes an experiment funnel metric and returns a series of events and actions
 * that can be used in a query.
 */
function getFunnelSeries(funnelMetric: ExperimentFunnelMetric): (EventsNode | ActionsNode)[] {
    const { events, actions } = metricToFilter(funnelMetric)

    return actionsAndEventsToSeries(
        {
            actions,
            events,
            data_warehouse: [],
        } as any,
        true,
        MathAvailability.None
    ).filter((series) => series.kind === NodeKind.EventsNode || series.kind === NodeKind.ActionsNode)
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
 * takes a metric and returns a filter that can be used as part of a query
 */
export function metricToFilter(metric: ExperimentMetric): FilterType {
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
             *
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

type MetricToInsightQueryOptions = {
    showTable: boolean
    showLastComputation: boolean
    showLastComputationRefresh: boolean
    queryOptions: Partial<MetricToQueryOptions>
}

/**
 * wraps an experiment metric into an InsightVizNode, by creating a query first.
 * this is the format that the Query component expects
 */
export function metricToInsightQuery(
    metric: ExperimentMetric,
    options?: Partial<MetricToInsightQueryOptions>
): InsightVizNode {
    const query = metricToQuery(metric, options?.queryOptions)

    if (!query) {
        throw new Error('Could not transform metric to query')
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

type ExposureConfigToEventsNodeOptions = {
    featureFlagKey: string
    featureFlagVariants: MultivariateFlagVariant[]
}

export function exposureConfigToEventsNode(
    exposureConfig: ExperimentEventExposureConfig,
    options: ExposureConfigToEventsNodeOptions
): EventsNode {
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

type Prettify<T> = {
    [K in keyof T]: T[K]
} & {}

export function getMetricWithExposureConfig(
    metric: ExperimentMetric,
    exposureConfig: ExperimentEventExposureConfig,
    options: ExposureConfigToEventsNodeOptions & Partial<Pick<MetricToInsightQueryOptions, 'queryOptions'>>
): FunnelsQuery | TrendsQuery {
    const { featureFlagKey, featureFlagVariants, queryOptions } = options
    const metricWithExposure = match(metric)
        .with({ metric_type: ExperimentMetricType.FUNNEL }, (funnelMetric) => {
            /**
             * we get the exposure event node
             */
            const exposureEventNode = exposureConfigToEventsNode(exposureConfig, {
                featureFlagKey,
                featureFlagVariants,
            })
            /**
             * we add the exposure event node to the funnel metric
             */
            return {
                ...funnelMetric,
                series: [exposureEventNode, ...funnelMetric.series],
            }
        })
        .otherwise(() => metric)

    const query = metricToQuery(metricWithExposure, queryOptions)

    if (!query) {
        throw new Error('Could not transform metric to query')
    }

    return query
}

export function getInsightWithExposure(
    metric: ExperimentMetric,
    exposureConfig: ExperimentEventExposureConfig,
    options: ExposureConfigToEventsNodeOptions & Partial<MetricToInsightQueryOptions>
): InsightVizNode {
    const query = getMetricWithExposureConfig(metric, exposureConfig, options)

    if (!query) {
        throw new Error('Could not transform metric to query')
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
