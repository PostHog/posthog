import { getSeriesColor } from 'lib/colors'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import merge from 'lodash.merge'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import {
    AnyEntityNode,
    EventsNode,
    ExperimentActionMetricConfig,
    ExperimentDataWarehouseMetricConfig,
    ExperimentEventExposureConfig,
    ExperimentEventMetricConfig,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentMetricMath,
    ExperimentMetricType,
    ExperimentTrendsQuery,
    type FunnelsQuery,
    NodeKind,
    type TrendsQuery,
} from '~/queries/schema/schema-general'
import { isFunnelsQuery, isNodeWithSource, isTrendsQuery, isValidQueryForExperiment } from '~/queries/utils'
import {
    BaseMathType,
    ChartDisplayType,
    FeatureFlagFilters,
    FeatureFlagType,
    FilterType,
    FunnelConversionWindowTimeUnit,
    FunnelTimeConversionMetrics,
    FunnelVizType,
    InsightType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
    type QueryBasedInsightModel,
    TrendResult,
    UniversalFiltersGroupValue,
} from '~/types'

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

export function getMinimumDetectableEffect(
    metricType: InsightType,
    conversionMetrics: FunnelTimeConversionMetrics,
    trendResults: TrendResult[]
): number | null {
    if (metricType === InsightType.FUNNELS) {
        // FUNNELS
        // Given current CR, find a realistic target CR increase and return MDE based on it
        if (!conversionMetrics) {
            return null
        }

        let currentConversionRate = conversionMetrics.totalRate * 100
        // 40% should have the same MDE as 60% -> perform a flip above 50%
        if (currentConversionRate > 50) {
            currentConversionRate = 100 - currentConversionRate
        }

        // Multiplication would result in 0; return MDE = 1
        if (currentConversionRate === 0) {
            return 1
        }

        // CR = 50% requires a high running time
        // CR = 1% or 99% requires a low running time
        const midpointDistance = Math.abs(50 - currentConversionRate)

        let targetConversionRateIncrease
        if (midpointDistance <= 20) {
            targetConversionRateIncrease = 0.1
        } else if (midpointDistance <= 35) {
            targetConversionRateIncrease = 0.2
        } else {
            targetConversionRateIncrease = 0.5
        }

        const targetConversionRate = Math.round(currentConversionRate * (1 + targetConversionRateIncrease))
        const mde = Math.ceil(targetConversionRate - currentConversionRate)

        return mde || 5
    }

    // TRENDS
    // Given current count of the Trend metric, what percentage increase are we targeting?
    if (trendResults[0]?.count === undefined) {
        return null
    }

    const baselineCount = trendResults[0].count

    if (baselineCount <= 200) {
        return 100
    } else if (baselineCount <= 1000) {
        return 20
    }
    return 5
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

function seriesToFilter(
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

export function getViewRecordingFilters(
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery,
    featureFlagKey: string,
    variantKey: string
): UniversalFiltersGroupValue[] {
    const filters: UniversalFiltersGroupValue[] = []
    if (metric.kind === NodeKind.ExperimentMetric) {
        if (metric.metric_config.kind === NodeKind.ExperimentEventMetricConfig) {
            return [
                {
                    id: metric.metric_config.event,
                    name: metric.metric_config.event,
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
        return []
    } else if (metric.kind === NodeKind.ExperimentTrendsQuery) {
        if (metric.exposure_query) {
            const exposure_filter = seriesToFilter(metric.exposure_query.series[0], featureFlagKey, variantKey)
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
        const count_filter = seriesToFilter(metric.count_query.series[0], featureFlagKey, variantKey)
        if (count_filter) {
            filters.push(count_filter)
        }
        return filters
    }
    metric.funnels_query.series.forEach((series) => {
        const filter = seriesToFilter(series, featureFlagKey, variantKey)
        if (filter) {
            filters.push(filter)
        }
    })
    return filters
}

export function featureFlagEligibleForExperiment(featureFlag: FeatureFlagType): true {
    if (featureFlag.experiment_set && featureFlag.experiment_set.length > 0) {
        throw new Error('Feature flag is already associated with an experiment.')
    }

    if (featureFlag.filters.multivariate?.variants?.length && featureFlag.filters.multivariate.variants.length > 1) {
        if (featureFlag.filters.multivariate.variants[0].key !== 'control') {
            throw new Error('Feature flag must have control as the first variant.')
        }
        return true
    }

    throw new Error('Feature flag must use multiple variants with control as the first variant.')
}

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

export function getDefaultFunnelMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.FUNNEL,
        metric_config: {
            kind: NodeKind.ExperimentEventMetricConfig,
            event: '$pageview',
        },
    }
}

export function getDefaultCountMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.COUNT,
        metric_config: {
            kind: NodeKind.ExperimentEventMetricConfig,
            event: '$pageview',
        },
    }
}

export function getDefaultContinuousMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.CONTINUOUS,
        metric_config: {
            kind: NodeKind.ExperimentEventMetricConfig,
            event: '$pageview',
            math: 'sum',
        },
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

export function metricConfigToFilter(
    metric_config: ExperimentEventMetricConfig | ExperimentActionMetricConfig | ExperimentDataWarehouseMetricConfig
): FilterType {
    if (metric_config.kind === NodeKind.ExperimentEventMetricConfig) {
        return {
            events: [
                {
                    id: metric_config.event,
                    name: metric_config.event,
                    kind: NodeKind.EventsNode,
                    type: 'events',
                    math: metric_config.math,
                    math_property: metric_config.math_property,
                    math_hogql: metric_config.math_hogql,
                    properties: metric_config.properties,
                } as EventsNode,
            ],
            actions: [],
            data_warehouse: [],
        }
    } else if (metric_config.kind === NodeKind.ExperimentActionMetricConfig) {
        return {
            events: [],
            actions: [
                {
                    id: metric_config.action,
                    name: metric_config.name,
                    kind: NodeKind.EventsNode,
                    type: 'actions',
                    math: metric_config.math,
                    math_property: metric_config.math_property,
                    math_hogql: metric_config.math_hogql,
                    properties: metric_config.properties,
                } as EventsNode,
            ],
            data_warehouse: [],
        }
    } else if (metric_config.kind === NodeKind.ExperimentDataWarehouseMetricConfig) {
        return {
            events: [],
            actions: [],
            data_warehouse: [
                {
                    kind: NodeKind.EventsNode,
                    type: 'data_warehouse',
                    id: metric_config.table_name,
                    name: metric_config.name,
                    timestamp_field: metric_config.timestamp_field,
                    events_join_key: metric_config.events_join_key,
                    data_warehouse_join_key: metric_config.data_warehouse_join_key,
                    math: metric_config.math,
                    math_property: metric_config.math_property,
                    math_hogql: metric_config.math_hogql,
                } as EventsNode,
            ],
        }
    }

    return {}
}

export function filterToMetricConfig(
    entity: Record<string, any> | undefined
): ExperimentEventMetricConfig | ExperimentActionMetricConfig | ExperimentDataWarehouseMetricConfig | undefined {
    if (!entity) {
        return undefined
    }

    if (entity.kind === NodeKind.EventsNode) {
        if (entity.type === 'events') {
            return {
                kind: NodeKind.ExperimentEventMetricConfig,
                event: entity.id as string,
                name: entity.name,
                math: (entity.math as ExperimentMetricMath) || 'total',
                math_property: entity.math_property,
                math_hogql: entity.math_hogql,
                properties: entity.properties,
            }
        } else if (entity.type === 'actions') {
            return {
                kind: NodeKind.ExperimentActionMetricConfig,
                action: entity.id,
                name: entity.name,
                math: (entity.math as ExperimentMetricMath) || 'total',
                math_property: entity.math_property,
                math_hogql: entity.math_hogql,
                properties: entity.properties,
            }
        } else if (entity.type === 'data_warehouse') {
            return {
                kind: NodeKind.ExperimentDataWarehouseMetricConfig,
                name: entity.name,
                table_name: entity.id,
                timestamp_field: entity.timestamp_field,
                events_join_key: entity.events_join_key,
                data_warehouse_join_key: entity.data_warehouse_join_key,
                math: (entity.math as ExperimentMetricMath) || 'total',
                math_property: entity.math_property,
                math_hogql: entity.math_hogql,
            }
        }
    }
}

export function metricToQuery(
    metric: ExperimentMetric,
    filterTestAccounts: boolean
): FunnelsQuery | TrendsQuery | undefined {
    const commonTrendsQueryProps: Partial<TrendsQuery> = {
        kind: NodeKind.TrendsQuery,
        interval: 'day',
        dateRange: {
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            explicitDate: true,
        },
        trendsFilter: {
            display: ChartDisplayType.ActionsLineGraph,
        },
        filterTestAccounts,
    }

    if (metric.metric_type === ExperimentMetricType.COUNT) {
        return {
            ...commonTrendsQueryProps,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    name: (metric.metric_config as ExperimentEventMetricConfig).name,
                    event: (metric.metric_config as ExperimentEventMetricConfig).event,
                },
            ],
        } as TrendsQuery
    } else if (metric.metric_type === ExperimentMetricType.CONTINUOUS) {
        return {
            ...commonTrendsQueryProps,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: (metric.metric_config as ExperimentEventMetricConfig).event,
                    name: (metric.metric_config as ExperimentEventMetricConfig).name,
                    math: PropertyMathType.Sum,
                    math_property: (metric.metric_config as ExperimentEventMetricConfig).math_property,
                },
            ],
        } as TrendsQuery
    } else if (metric.metric_type === ExperimentMetricType.FUNNEL) {
        return {
            kind: NodeKind.FunnelsQuery,
            filterTestAccounts,
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            funnelsFilter: {
                layout: FunnelLayout.horizontal,
            },
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$feature_flag_called',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: (metric.metric_config as ExperimentEventMetricConfig).event,
                },
            ],
        } as FunnelsQuery
    }

    return undefined
}

export function getMathAvailability(metricType: ExperimentMetricType): MathAvailability {
    switch (metricType) {
        case ExperimentMetricType.COUNT:
            return MathAvailability.None
        case ExperimentMetricType.CONTINUOUS:
            return MathAvailability.All
        default:
            return MathAvailability.None
    }
}

export function getAllowedMathTypes(metricType: ExperimentMetricType): string[] {
    switch (metricType) {
        case ExperimentMetricType.COUNT:
            return [BaseMathType.TotalCount]
        case ExperimentMetricType.CONTINUOUS:
            return [PropertyMathType.Sum]
        default:
            return [BaseMathType.TotalCount]
    }
}
