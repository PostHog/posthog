import { getSeriesColor } from 'lib/colors'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import merge from 'lodash.merge'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import {
    ActionsNode,
    AnyEntityNode,
    EventsNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetricStep,
    ExperimentFunnelMetricTypeProps,
    ExperimentFunnelsQuery,
    ExperimentMeanMetricTypeProps,
    ExperimentMetric,
    ExperimentMetricType,
    ExperimentMetricTypeProps,
    ExperimentTrendsQuery,
    type FunnelsQuery,
    NodeKind,
    type TrendsQuery,
} from '~/queries/schema/schema-general'
import { isFunnelsQuery, isNodeWithSource, isTrendsQuery, isValidQueryForExperiment } from '~/queries/utils'
import {
    ChartDisplayType,
    Experiment,
    ExperimentMetricMathType,
    FeatureFlagFilters,
    FeatureFlagType,
    FilterType,
    FunnelConversionWindowTimeUnit,
    FunnelVizType,
    PropertyFilterType,
    PropertyOperator,
    type QueryBasedInsightModel,
    UniversalFiltersGroupValue,
} from '~/types'

import { SharedMetric } from './SharedMetrics/sharedMetricLogic'

export function getExperimentInsightColour(variantIndex: number | null): string {
    return variantIndex !== null ? getSeriesColor(variantIndex) : 'var(--muted-3000)'
}

export function formatUnitByQuantity(value: number, unit: string): string {
    return value === 1 ? unit : unit + 's'
}

export function percentageDistribution(variantCount: number): number[] {
    const basePercentage = Math.floor(100 / variantCount)
    const percentages = new Array(variantCount).fill(basePercentage)
    let remaining = 100 - basePercentage * variantCount
    for (let i = 0; remaining > 0; i++, remaining--) {
        // try to equally distribute `remaining` across variants
        percentages[i] += 1
    }
    return percentages
}

export function transformFiltersForWinningVariant(
    currentFlagFilters: FeatureFlagFilters,
    selectedVariant: string
): FeatureFlagFilters {
    return {
        aggregation_group_type_index: currentFlagFilters?.aggregation_group_type_index || null,
        payloads: currentFlagFilters?.payloads || {},
        multivariate: {
            variants: (currentFlagFilters?.multivariate?.variants || []).map(({ key, name }) => ({
                key,
                rollout_percentage: key === selectedVariant ? 100 : 0,
                ...(name && { name }),
            })),
        },
        groups: [
            { properties: [], rollout_percentage: 100 },
            // Preserve existing groups so that users can roll back this action
            // by deleting the newly added release condition
            ...(currentFlagFilters?.groups || []),
        ],
    }
}

function seriesToFilterLegacy(
    series: AnyEntityNode,
    featureFlagKey: string,
    variantKey: string
): UniversalFiltersGroupValue | null {
    if (series.kind === NodeKind.EventsNode) {
        return {
            id: series.event as string,
            name: series.event as string,
            type: 'events',
            properties: [
                {
                    key: `$feature/${featureFlagKey}`,
                    type: PropertyFilterType.Event,
                    value: [variantKey],
                    operator: PropertyOperator.Exact,
                },
            ],
        }
    } else if (series.kind === NodeKind.ActionsNode) {
        return {
            id: series.id,
            name: series.name,
            type: 'actions',
        }
    }
    return null
}

function seriesToFilter(series: AnyEntityNode): UniversalFiltersGroupValue | null {
    if (series.kind === NodeKind.EventsNode) {
        return {
            id: series.event ?? null,
            name: series.event as string,
            type: 'events',
            properties: series.properties ?? [],
        }
    }

    if (series.kind === NodeKind.ActionsNode) {
        return {
            id: series.id,
            name: series.name,
            type: 'actions',
        }
    }

    return null
}
/**
 * Gets the Filters to ExperimentMetrics, Can't quite use `exposureConfigToFilter` or
 * `metricToFilter` because the format is not quite the same, but we can use `seriesToFilter`
 *
 * TODO: refactor the *ToFilter functions so we can use bits of them.
 */
export function getViewRecordingFilters(
    experiment: Experiment,
    metric: ExperimentMetric,
    variantKey: string
): UniversalFiltersGroupValue[] {
    const filters: UniversalFiltersGroupValue[] = []
    /**
     * We need to check the exposure criteria as the first on the filter chain.
     * exposure criteria can only be events, not actions
     */
    const exposureCriteria = experiment.exposure_criteria?.exposure_config
    if (exposureCriteria && exposureCriteria.event !== '$feature_flag_called') {
        filters.push({
            id: exposureCriteria.event,
            name: exposureCriteria.event,
            type: 'events',
            properties: [
                ...(exposureCriteria.properties || []),
                {
                    key: `$feature/${experiment.feature_flag_key}`,
                    type: PropertyFilterType.Event,
                    value: [variantKey],
                    operator: PropertyOperator.Exact,
                },
            ],
        })
    } else {
        filters.push({
            id: '$feature_flag_called',
            name: '$feature_flag_called',
            type: 'events',
            properties: [
                {
                    key: '$feature_flag_response',
                    type: PropertyFilterType.Event,
                    value: [variantKey],
                    operator: PropertyOperator.Exact,
                },
                {
                    key: '$feature_flag',
                    type: PropertyFilterType.Event,
                    value: experiment.feature_flag_key,
                    operator: PropertyOperator.Exact,
                },
            ],
        })
    }

    /**
     * for mean metrics, we add the single action/event to the filters
     */
    if (
        metric.metric_type === ExperimentMetricType.MEAN &&
        (metric.source.kind === NodeKind.EventsNode || metric.source.kind === NodeKind.ActionsNode)
    ) {
        const meanFilter = seriesToFilter(metric.source)
        if (meanFilter) {
            filters.push(meanFilter)
        }
    }

    /**
     * for funnel metrics, we need to add each element in the series as a filter
     */
    if (metric.metric_type === ExperimentMetricType.FUNNEL) {
        metric.series.forEach((series) => {
            const funnelMetric = seriesToFilter(series)
            if (funnelMetric) {
                filters.push(funnelMetric)
            }
        })
    }

    return filters
}

export function getViewRecordingFiltersLegacy(
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery,
    featureFlagKey: string,
    variantKey: string
): UniversalFiltersGroupValue[] {
    const filters: UniversalFiltersGroupValue[] = []
    if (metric.kind === NodeKind.ExperimentMetric) {
        if (metric.metric_type === ExperimentMetricType.MEAN) {
            if (metric.source.kind === NodeKind.EventsNode) {
                return [
                    {
                        id: metric.source.event ?? null,
                        name: metric.source.event,
                        type: 'events',
                        properties: [
                            {
                                key: `$feature/${featureFlagKey}`,
                                type: PropertyFilterType.Event,
                                value: [variantKey],
                                operator: PropertyOperator.Exact,
                            },
                        ],
                    },
                ]
            }
        }
        return []
    } else if (metric.kind === NodeKind.ExperimentTrendsQuery) {
        if (metric.exposure_query) {
            const exposure_filter = seriesToFilterLegacy(metric.exposure_query.series[0], featureFlagKey, variantKey)
            if (exposure_filter) {
                filters.push(exposure_filter)
            }
        } else {
            filters.push({
                id: '$feature_flag_called',
                name: '$feature_flag_called',
                type: 'events',
                properties: [
                    {
                        key: `$feature_flag_response`,
                        type: PropertyFilterType.Event,
                        value: [variantKey],
                        operator: PropertyOperator.Exact,
                    },
                    {
                        key: '$feature_flag',
                        type: PropertyFilterType.Event,
                        value: featureFlagKey,
                        operator: PropertyOperator.Exact,
                    },
                ],
            })
        }
        const count_filter = seriesToFilterLegacy(metric.count_query.series[0], featureFlagKey, variantKey)
        if (count_filter) {
            filters.push(count_filter)
        }
        return filters
    }
    metric.funnels_query.series.forEach((series) => {
        const filter = seriesToFilterLegacy(series, featureFlagKey, variantKey)
        if (filter) {
            filters.push(filter)
        }
    })
    return filters
}

export function featureFlagEligibleForExperiment(featureFlag: FeatureFlagType): true {
    if (featureFlag.filters.multivariate?.variants?.length && featureFlag.filters.multivariate.variants.length > 1) {
        if (featureFlag.filters.multivariate.variants[0].key !== 'control') {
            throw new Error('Feature flag must have control as the first variant.')
        }
        return true
    }

    throw new Error('Feature flag must use multiple variants with control as the first variant.')
}

/**
 * TODO: review. Probably deprecated
 */
export function getDefaultTrendsMetric(): ExperimentTrendsQuery {
    return {
        kind: NodeKind.ExperimentTrendsQuery,
        count_query: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    name: '$pageview',
                    event: '$pageview',
                },
            ],
            interval: 'day',
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
            },
            filterTestAccounts: true,
        },
    }
}

export function getDefaultFunnelsMetric(): ExperimentFunnelsQuery {
    return {
        kind: NodeKind.ExperimentFunnelsQuery,
        funnels_query: {
            kind: NodeKind.FunnelsQuery,
            filterTestAccounts: true,
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                },
            ],
            funnelsFilter: {
                funnelVizType: FunnelVizType.Steps,
                funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                funnelWindowInterval: 14,
                layout: FunnelLayout.horizontal,
            },
        },
    }
}

/**
 * TODO: review. Probably deprecated
 */
export function getDefaultFunnelMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.FUNNEL,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
            },
        ],
    }
}

/**
 * @deprecated
 */
export function getDefaultCountMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.MEAN,
        source: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
    }
}

/**
 * TODO: review. Probably deprecated
 */
export function getDefaultExperimentMetric(metricType: ExperimentMetricType): ExperimentMetric {
    switch (metricType) {
        case ExperimentMetricType.FUNNEL:
            return getDefaultFunnelMetric()
        default:
            return getDefaultCountMetric()
    }
}

export function getExperimentMetricFromInsight(
    insight: QueryBasedInsightModel | null
): ExperimentTrendsQuery | ExperimentFunnelsQuery | undefined {
    if (!insight?.query || !isValidQueryForExperiment(insight?.query) || !isNodeWithSource(insight.query)) {
        return undefined
    }

    const metricName = (insight?.name || insight?.derived_name) ?? undefined

    if (isFunnelsQuery(insight.query.source)) {
        const defaultFunnelsQuery = getDefaultFunnelsMetric().funnels_query

        const funnelsQuery: FunnelsQuery = merge(defaultFunnelsQuery, {
            series: insight.query.source.series,
            funnelsFilter: {
                funnelAggregateByHogQL: insight.query.source.funnelsFilter?.funnelAggregateByHogQL,
                funnelWindowInterval: insight.query.source.funnelsFilter?.funnelWindowInterval,
                funnelWindowIntervalUnit: insight.query.source.funnelsFilter?.funnelWindowIntervalUnit,
                layout: insight.query.source.funnelsFilter?.layout,
                breakdownAttributionType: insight.query.source.funnelsFilter?.breakdownAttributionType,
                breakdownAttributionValue: insight.query.source.funnelsFilter?.breakdownAttributionValue,
                funnelOrderType: insight.query.source.funnelsFilter?.funnelOrderType,
            },
            filterTestAccounts: insight.query.source.filterTestAccounts,
        })

        return {
            kind: NodeKind.ExperimentFunnelsQuery,
            funnels_query: funnelsQuery,
            name: metricName,
        }
    }

    if (isTrendsQuery(insight.query.source)) {
        const defaultTrendsQuery = getDefaultTrendsMetric().count_query

        const trendsQuery: TrendsQuery = merge(defaultTrendsQuery, {
            series: insight.query.source.series,
            filterTestAccounts: insight.query.source.filterTestAccounts,
        })

        return {
            kind: NodeKind.ExperimentTrendsQuery,
            count_query: trendsQuery,
            name: metricName,
        }
    }

    return undefined
}

/**
 * Used when setting a custom exposure criteria
 */
export function exposureConfigToFilter(exposure_config: ExperimentEventExposureConfig): FilterType {
    if (exposure_config.kind === NodeKind.ExperimentEventExposureConfig) {
        return {
            events: [
                {
                    id: exposure_config.event,
                    name: exposure_config.event,
                    kind: NodeKind.EventsNode,
                    type: 'events',
                    properties: exposure_config.properties,
                } as EventsNode,
            ],
            actions: [],
            data_warehouse: [],
        }
    }

    return {}
}

/**
 * Used when setting a custom exposure criteria
 */
export function filterToExposureConfig(
    entity: Record<string, any> | undefined
): ExperimentEventExposureConfig | undefined {
    if (!entity) {
        return undefined
    }

    if (entity.kind === NodeKind.EventsNode) {
        if (entity.type === 'events') {
            return {
                kind: NodeKind.ExperimentEventExposureConfig,
                event: entity.id,
                properties: entity.properties,
            }
        }
    }

    return undefined
}

/**
 * TODO: review for refactor.
 */
export function filterToMetricConfig(
    metricType: ExperimentMetricType,
    actions: Record<string, any>[] | undefined,
    events: Record<string, any>[] | undefined,
    data_warehouse: Record<string, any>[] | undefined
): ExperimentMetricTypeProps | undefined {
    const getFunnelMetricConfig = (): ExperimentFunnelMetricTypeProps | undefined => {
        if (metricType !== ExperimentMetricType.FUNNEL) {
            return undefined
        }

        // Combine events and actions and sort by order
        const eventSteps =
            events?.map(
                (event) =>
                    ({
                        kind: NodeKind.EventsNode,
                        event: event.id,
                        properties: event.properties,
                        order: event.order,
                    } as EventsNode & { order: number })
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
                    } as ActionsNode & { order: number })
            ) || []

        const combinedSteps = [...eventSteps, ...actionSteps].sort((a, b) => a.order - b.order)

        // Remove the temporary order field
        const series = combinedSteps.map(({ order, ...step }) => step as ExperimentFunnelMetricStep)

        return {
            metric_type: ExperimentMetricType.FUNNEL,
            series,
        }
    }

    const getEventMetricConfig = (): ExperimentMeanMetricTypeProps | undefined => {
        if (metricType !== ExperimentMetricType.MEAN || !events?.[0]) {
            return undefined
        }

        return {
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: events[0].id,
                name: events[0].name,
                math: events[0].math || ExperimentMetricMathType.TotalCount,
                math_property: events[0].math_property,
                math_hogql: events[0].math_hogql,
                properties: events[0].properties,
            },
        }
    }

    const getActionMetricConfig = (): ExperimentMeanMetricTypeProps | undefined => {
        if (metricType !== ExperimentMetricType.MEAN || !actions?.[0]) {
            return undefined
        }

        return {
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: actions[0].id,
                name: actions[0].name,
                math: actions[0].math || ExperimentMetricMathType.TotalCount,
                math_property: actions[0].math_property,
                math_hogql: actions[0].math_hogql,
                properties: actions[0].properties,
            },
        }
    }

    const getDataWarehouseMetricConfig = (): ExperimentMeanMetricTypeProps | undefined => {
        if (metricType !== ExperimentMetricType.MEAN || !data_warehouse?.[0]) {
            return undefined
        }

        return {
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ExperimentDataWarehouseNode,
                name: data_warehouse[0].name,
                table_name: data_warehouse[0].id,
                timestamp_field: data_warehouse[0].timestamp_field,
                events_join_key: data_warehouse[0].events_join_key,
                data_warehouse_join_key: data_warehouse[0].data_warehouse_join_key,
                math: data_warehouse[0].math || ExperimentMetricMathType.TotalCount,
                math_property: data_warehouse[0].math_property,
                math_hogql: data_warehouse[0].math_hogql,
                properties: data_warehouse[0].properties,
            },
        }
    }

    // Return the first non-undefined configuration
    return (
        getFunnelMetricConfig() || getEventMetricConfig() || getActionMetricConfig() || getDataWarehouseMetricConfig()
    )
}

/**
 * returns the math availability for a metric type
 */
export function getMathAvailability(metricType: ExperimentMetricType): MathAvailability {
    switch (metricType) {
        case ExperimentMetricType.MEAN:
            return MathAvailability.All
        default:
            return MathAvailability.None
    }
}

/**
 * returns the allowed math types that can be used when creating a metric
 */
export function getAllowedMathTypes(metricType: ExperimentMetricType): ExperimentMetricMathType[] {
    switch (metricType) {
        case ExperimentMetricType.MEAN:
            return [
                ExperimentMetricMathType.TotalCount,
                ExperimentMetricMathType.Sum,
                ExperimentMetricMathType.Avg,
                ExperimentMetricMathType.Min,
                ExperimentMetricMathType.Max,
                ExperimentMetricMathType.UniqueSessions,
                ExperimentMetricMathType.HogQL,
            ]
        default:
            return [ExperimentMetricMathType.TotalCount]
    }
}

/**
 * Check if a query is a legacy experiment metric.
 *
 * We use `unknown` here because in some cases, the query is not typed.
 */
export const isLegacyExperimentQuery = (query: unknown): query is ExperimentTrendsQuery | ExperimentFunnelsQuery => {
    /**
     * since query could be an object literal type, we need to check for the kind property
     */
    return (
        !!query &&
        typeof query === 'object' &&
        'kind' in query &&
        (query.kind === NodeKind.ExperimentTrendsQuery || query.kind === NodeKind.ExperimentFunnelsQuery)
    )
}

/**
 * The legacy query runner uses ExperimentTrendsQuery and ExperimentFunnelsQuery
 * to run experiments.
 *
 * We should remove these legacy metrics once we've migrated all experiments to the new query runner.
 */
export const isLegacyExperiment = ({ metrics, metrics_secondary, saved_metrics }: Experiment): boolean => {
    // saved_metrics has a different structure and so we need to check for it separately
    if (saved_metrics.some(isLegacySharedMetric)) {
        return true
    }
    return [...metrics, ...metrics_secondary].some(isLegacyExperimentQuery)
}

export const isLegacySharedMetric = ({ query }: SharedMetric): boolean => isLegacyExperimentQuery(query)
