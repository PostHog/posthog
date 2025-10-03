import { getSeriesColor } from 'lib/colors'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import {
    AnyEntityNode,
    EventsNode,
    ExperimentEventExposureConfig,
    ExperimentExposureConfig,
    ExperimentFunnelMetricStep,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentMetricSource,
    ExperimentMetricType,
    ExperimentTrendsQuery,
    NodeKind,
    TrendsQuery,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { isFunnelsQuery, isNodeWithSource, isTrendsQuery, isValidQueryForExperiment } from '~/queries/utils'
import {
    ChartDisplayType,
    Experiment,
    ExperimentMetricGoal,
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

export function isEventExposureConfig(config: ExperimentExposureConfig): config is ExperimentEventExposureConfig {
    return config.kind === NodeKind.ExperimentEventExposureConfig || 'event' in config
}

export function getExposureConfigDisplayName(config: ExperimentExposureConfig): string {
    return isEventExposureConfig(config) ? config.event || 'Unknown Event' : config.name || `Action ${config.id}`
}

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

function seriesToFilter(series: AnyEntityNode | ExperimentMetricSource): UniversalFiltersGroupValue | null {
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

    if (series.kind === NodeKind.ExperimentDataWarehouseNode) {
        return {
            id: series.table_name,
            name: series.name,
            type: 'data_warehouse',
        }
    }

    return null
}

function createExposureFilter(
    exposureConfig: ExperimentExposureConfig,
    featureFlagKey: string,
    variantKey: string
): UniversalFiltersGroupValue {
    const isEvent = isEventExposureConfig(exposureConfig)
    return {
        id: isEvent ? exposureConfig.event || 'unknown' : exposureConfig.id,
        name: isEvent ? exposureConfig.event || 'Unknown Event' : exposureConfig.name || `Action ${exposureConfig.id}`,
        type: isEvent ? 'events' : 'actions',
        properties: [
            ...(exposureConfig.properties || []),
            {
                key: `$feature/${featureFlagKey}`,
                type: PropertyFilterType.Event,
                value: [variantKey],
                operator: PropertyOperator.Exact,
            },
        ],
    }
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
     */
    const exposureCriteria = experiment.exposure_criteria?.exposure_config
    if (
        exposureCriteria &&
        !(isEventExposureConfig(exposureCriteria) && exposureCriteria.event === '$feature_flag_called')
    ) {
        filters.push(createExposureFilter(exposureCriteria, experiment.feature_flag_key, variantKey))
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
        isExperimentMeanMetric(metric) &&
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
    if (isExperimentFunnelMetric(metric)) {
        metric.series.forEach((series) => {
            const funnelMetric = seriesToFilter(series)
            if (funnelMetric) {
                filters.push(funnelMetric)
            }
        })
    }

    /**
     * for ratio metrics, we add both numerator and denominator events to the filters
     */
    if (isExperimentRatioMetric(metric)) {
        const numeratorFilter = seriesToFilter(metric.numerator)
        const denominatorFilter = seriesToFilter(metric.denominator)

        if (numeratorFilter) {
            filters.push(numeratorFilter)
        }
        if (denominatorFilter) {
            filters.push(denominatorFilter)
        }
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
        if (isExperimentMeanMetric(metric)) {
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
        uuid: uuid(),
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
        uuid: uuid(),
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
        uuid: uuid(),
        metric_type: ExperimentMetricType.FUNNEL,
        goal: ExperimentMetricGoal.Increase,
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
        uuid: uuid(),
        metric_type: ExperimentMetricType.MEAN,
        goal: ExperimentMetricGoal.Increase,
        source: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
    }
}

export function getDefaultRatioMetric(): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        uuid: uuid(),
        metric_type: ExperimentMetricType.RATIO,
        goal: ExperimentMetricGoal.Increase,
        numerator: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
        denominator: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            math: ExperimentMetricMathType.TotalCount,
        },
    }
}

export function getDefaultExperimentMetric(metricType: ExperimentMetricType): ExperimentMetric {
    switch (metricType) {
        case ExperimentMetricType.FUNNEL:
            return getDefaultFunnelMetric()
        case ExperimentMetricType.RATIO:
            return getDefaultRatioMetric()
        default:
            return getDefaultCountMetric()
    }
}

export function getExperimentMetricFromInsight(insight: QueryBasedInsightModel | null): ExperimentMetric | undefined {
    if (!insight?.query || !isValidQueryForExperiment(insight?.query) || !isNodeWithSource(insight.query)) {
        return undefined
    }

    const metricName = (insight?.name || insight?.derived_name) ?? undefined

    if (isFunnelsQuery(insight.query.source)) {
        return {
            kind: NodeKind.ExperimentMetric,
            uuid: uuid(),
            metric_type: ExperimentMetricType.FUNNEL,
            goal: ExperimentMetricGoal.Increase,
            name: metricName,
            series: insight.query.source.series.map((series) => ({
                ...series,
                // Ensure we have proper node structure
                kind: series.kind || NodeKind.EventsNode,
                event: series.kind === NodeKind.EventsNode ? series.event : undefined,
                name: series.name || (series.kind === NodeKind.EventsNode ? series.event : undefined),
            })) as ExperimentFunnelMetricStep[],
        }
    }

    /**
     * TODO: add support for trends queries. IsValidQueryForExperiment
     * has a isFunnelsQuery check, so this is never called. Trend queries
     * get undefined.
     */
    if (isTrendsQuery(insight.query.source)) {
        // For trends queries, convert the first series to a mean metric
        const firstSeries = insight.query.source.series?.[0]
        if (!firstSeries) {
            return undefined
        }

        return {
            kind: NodeKind.ExperimentMetric,
            uuid: uuid(),
            metric_type: ExperimentMetricType.MEAN,
            goal: ExperimentMetricGoal.Increase,
            name: metricName,
            source: {
                ...firstSeries,
                kind: NodeKind.EventsNode,
                event: firstSeries.name,
                name: firstSeries.name,
                math: firstSeries.math || ExperimentMetricMathType.TotalCount,
            },
        }
    }

    return undefined
}

/**
 * Used when setting a custom exposure criteria
 */
export function exposureConfigToFilter(exposure_config: ExperimentExposureConfig): FilterType {
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
    if (exposure_config.kind === NodeKind.ActionsNode) {
        return {
            events: [],
            actions: [
                {
                    id: exposure_config.id,
                    name: exposure_config.name || '',
                    kind: NodeKind.ActionsNode,
                    type: 'actions' as const,
                    properties: exposure_config.properties,
                },
            ],
            data_warehouse: [],
        }
    }

    return {}
}

/**
 * Used when setting a custom exposure criteria
 */
export function filterToExposureConfig(entity: Record<string, any> | undefined): ExperimentExposureConfig | undefined {
    if (!entity) {
        return undefined
    }

    // Check type first since ActionFilter may set kind incorrectly
    if (entity.type === 'actions') {
        return {
            kind: NodeKind.ActionsNode,
            id: entity.id,
            name: entity.name,
            properties: entity.properties,
        }
    }

    if (entity.type === 'events' || entity.kind === NodeKind.EventsNode) {
        return {
            kind: NodeKind.ExperimentEventExposureConfig,
            event: entity.id,
            properties: entity.properties,
        }
    }

    return undefined
}

/**
 * returns the math availability for a metric type
 */
export function getMathAvailability(metricType: ExperimentMetricType): MathAvailability {
    switch (metricType) {
        case ExperimentMetricType.MEAN:
        case ExperimentMetricType.RATIO:
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
                ExperimentMetricMathType.UniqueUsers,
                ExperimentMetricMathType.UniqueGroup,
                ExperimentMetricMathType.Avg,
                ExperimentMetricMathType.Min,
                ExperimentMetricMathType.Max,
                ExperimentMetricMathType.UniqueSessions,
                ExperimentMetricMathType.HogQL,
            ]
        case ExperimentMetricType.RATIO:
            return [
                ExperimentMetricMathType.TotalCount,
                ExperimentMetricMathType.Sum,
                ExperimentMetricMathType.UniqueUsers,
                ExperimentMetricMathType.UniqueGroup,
                ExperimentMetricMathType.UniqueSessions,
                ExperimentMetricMathType.Avg,
                ExperimentMetricMathType.Min,
                ExperimentMetricMathType.Max,
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

/**
 * Builds a TrendsQuery for counting events in the last 14 days for experiment metric preview
 */
export function getEventCountQuery(metric: ExperimentMetric, filterTestAccounts: boolean): TrendsQuery | null {
    let series: AnyEntityNode[] = []

    if (isExperimentMeanMetric(metric) || isExperimentRatioMetric(metric)) {
        let source: ExperimentMetricSource
        // For now, we simplify things by just showing the number of numerator events for ratio metrics
        if (isExperimentRatioMetric(metric)) {
            source = metric.numerator
        } else {
            source = metric.source
        }
        if (source.kind === NodeKind.EventsNode) {
            series = [
                {
                    kind: NodeKind.EventsNode,
                    name: source.event || undefined,
                    event: source.event || undefined,
                    math: ExperimentMetricMathType.TotalCount,
                    ...(source.properties && source.properties.length > 0 && { properties: source.properties }),
                },
            ]
        } else if (source.kind === NodeKind.ActionsNode) {
            series = [
                {
                    kind: NodeKind.ActionsNode,
                    id: source.id,
                    name: source.name,
                    math: ExperimentMetricMathType.TotalCount,
                    ...(source.properties && source.properties.length > 0 && { properties: source.properties }),
                },
            ]
        } else if (source.kind === NodeKind.ExperimentDataWarehouseNode) {
            series = [
                {
                    kind: NodeKind.DataWarehouseNode,
                    id: source.table_name,
                    id_field: source.data_warehouse_join_key,
                    table_name: source.table_name,
                    timestamp_field: source.timestamp_field,
                    distinct_id_field: source.events_join_key,
                    name: source.name,
                    math: ExperimentMetricMathType.TotalCount,
                    ...(source.properties && source.properties.length > 0 && { properties: source.properties }),
                },
            ]
        }
    } else if (isExperimentFunnelMetric(metric)) {
        const lastStep = metric.series[metric.series.length - 1]
        if (lastStep) {
            if (lastStep.kind === NodeKind.EventsNode) {
                series = [
                    {
                        kind: NodeKind.EventsNode,
                        name: lastStep.event || undefined,
                        event: lastStep.event,
                        math: ExperimentMetricMathType.TotalCount,
                        ...(lastStep.properties &&
                            lastStep.properties.length > 0 && { properties: lastStep.properties }),
                    },
                ]
            } else if (lastStep.kind === NodeKind.ActionsNode) {
                series = [
                    {
                        kind: NodeKind.ActionsNode,
                        id: lastStep.id,
                        name: lastStep.name,
                        math: ExperimentMetricMathType.TotalCount,
                        ...(lastStep.properties &&
                            lastStep.properties.length > 0 && { properties: lastStep.properties }),
                    },
                ]
            }
        }
    }

    if (series.length === 0) {
        return null
    }

    return {
        kind: NodeKind.TrendsQuery,
        series,
        trendsFilter: {
            formulaNodes: [],
            display: ChartDisplayType.BoldNumber,
        },
        dateRange: {
            date_from: '-14d',
            date_to: null,
            explicitDate: false,
        },
        interval: 'day',
        filterTestAccounts,
    }
}

/**
 * Appends a metric UUID to the appropriate ordering array
 * Returns a new array with the UUID added
 */
export function appendMetricToOrderingArray(experiment: Experiment, uuid: string, isSecondary: boolean): string[] {
    const orderingField = isSecondary ? 'secondary_metrics_ordered_uuids' : 'primary_metrics_ordered_uuids'
    const orderingArray = experiment[orderingField] ?? []

    if (!orderingArray.includes(uuid)) {
        return [...orderingArray, uuid]
    }

    return orderingArray
}

/**
 * Removes a metric UUID from the appropriate ordering array
 * Returns a new array with the UUID removed
 */
export function removeMetricFromOrderingArray(experiment: Experiment, uuid: string, isSecondary: boolean): string[] {
    const orderingField = isSecondary ? 'secondary_metrics_ordered_uuids' : 'primary_metrics_ordered_uuids'
    const orderingArray = experiment[orderingField] ?? []

    return orderingArray.filter((existingUuid) => existingUuid !== uuid)
}

/**
 * Inserts a metric UUID into the ordering array right after another UUID
 * Returns a new array with the UUID inserted at the correct position
 */
export function insertMetricIntoOrderingArray(
    experiment: Experiment,
    newUuid: string,
    afterUuid: string,
    isSecondary: boolean
): string[] {
    const orderingField = isSecondary ? 'secondary_metrics_ordered_uuids' : 'primary_metrics_ordered_uuids'
    const orderingArray = experiment[orderingField] ?? []

    const afterIndex = orderingArray.indexOf(afterUuid)

    const newArray = [...orderingArray]
    newArray.splice(afterIndex + 1, 0, newUuid)
    return newArray
}

/**
 * Initialize ordering arrays for metrics if they're null
 * Returns a new experiment object with initialized ordering arrays
 */
export function initializeMetricOrdering(experiment: Experiment): Experiment {
    const newExperiment = { ...experiment }

    // Initialize primary_metrics_ordered_uuids if it's null
    if (newExperiment.primary_metrics_ordered_uuids === null) {
        const primaryMetrics = newExperiment.metrics || []
        const sharedPrimaryMetrics = (newExperiment.saved_metrics || []).filter(
            (sharedMetric: any) => sharedMetric.metadata.type === 'primary'
        )

        const allMetrics = [...primaryMetrics, ...sharedPrimaryMetrics]
        newExperiment.primary_metrics_ordered_uuids = allMetrics
            .map((metric: any) => metric.uuid || metric.query?.uuid)
            .filter(Boolean)
    }

    // Initialize secondary_metrics_ordered_uuids if it's null
    if (newExperiment.secondary_metrics_ordered_uuids === null) {
        const secondaryMetrics = newExperiment.metrics_secondary || []
        const sharedSecondaryMetrics = (newExperiment.saved_metrics || []).filter(
            (sharedMetric: any) => sharedMetric.metadata.type === 'secondary'
        )

        const allMetrics = [...secondaryMetrics, ...sharedSecondaryMetrics]
        newExperiment.secondary_metrics_ordered_uuids = allMetrics
            .map((metric: any) => metric.uuid || metric.query?.uuid)
            .filter(Boolean)
    }

    return newExperiment
}
