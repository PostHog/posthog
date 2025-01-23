import { getSeriesColor } from 'lib/colors'

import { ExperimentFunnelsQuery, ExperimentTrendsQuery } from '~/queries/schema'
import { AnyEntityNode, NodeKind } from '~/queries/schema/schema-general'
import {
    FeatureFlagFilters,
    FunnelTimeConversionMetrics,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
    TrendResult,
    UniversalFiltersGroupValue,
} from '~/types'

export function getExperimentInsightColour(variantIndex: number | null): string {
    return variantIndex !== null ? getSeriesColor(variantIndex) : 'var(--muted-3000)'
}

export function formatUnitByQuantity(value: number, unit: string): string {
    return value === 1 ? unit : unit + 's'
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
    metric: ExperimentTrendsQuery | ExperimentFunnelsQuery,
    featureFlagKey: string,
    variantKey: string
): UniversalFiltersGroupValue[] {
    const filters: UniversalFiltersGroupValue[] = []
    if (metric.kind === NodeKind.ExperimentTrendsQuery) {
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
