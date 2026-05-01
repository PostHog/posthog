import {
    ExperimentTrendsQuery,
    ExperimentFunnelsQuery,
    NodeKind,
    CachedLegacyExperimentQueryResponse,
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
} from '~/queries/schema/schema-general'
import {
    CountPerActorMathType,
    Experiment,
    FunnelExperimentVariant,
    InsightType,
    PropertyMathType,
    TrendExperimentVariant,
} from '~/types'

import { legacyGetSignificanceDetails } from './calculations/legacyExperimentCalculations'

/**
 * @deprecated
 * Use the getInsightType function from the experimentLogic instead.
 */
export const getInsightType = (metric: ExperimentTrendsQuery | ExperimentFunnelsQuery): InsightType => {
    return metric.kind === NodeKind.ExperimentTrendsQuery ? InsightType.TRENDS : InsightType.FUNNELS
}

/**
 * @deprecated
 * Use the tabularExperimentResults function from the experimentLogic instead.
 */
export const getTabularExperimentResults =
    (
        experiment: Experiment,
        legacyPrimaryMetricsResults: (
            | CachedLegacyExperimentQueryResponse
            | CachedExperimentFunnelsQueryResponse
            | CachedExperimentTrendsQueryResponse
            | null
        )[],
        legacySecondaryMetricsResults: (
            | CachedLegacyExperimentQueryResponse
            | CachedExperimentFunnelsQueryResponse
            | CachedExperimentTrendsQueryResponse
            | null
        )[],
        getInsightType: (metric: ExperimentTrendsQuery | ExperimentFunnelsQuery) => InsightType
    ) =>
    (metricIdentifier: number | string = 0, isSecondary: boolean = false): any[] => {
        let index: number
        if (typeof metricIdentifier === 'string') {
            // Find index by UUID
            const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
            index = metrics.findIndex((m) => m.uuid === metricIdentifier)
            if (index === -1) {
                return []
            }
        } else {
            index = metricIdentifier
        }

        const tabularResults = []
        const metricType = isSecondary
            ? getInsightType(experiment.metrics_secondary[index] as ExperimentTrendsQuery | ExperimentFunnelsQuery)
            : getInsightType(experiment.metrics[index] as ExperimentTrendsQuery | ExperimentFunnelsQuery)
        const result = isSecondary ? legacySecondaryMetricsResults[index] : legacyPrimaryMetricsResults[index]

        if (result) {
            for (const variantObj of result.variants) {
                if (metricType === InsightType.FUNNELS) {
                    const { key, success_count, failure_count } = variantObj as FunnelExperimentVariant
                    tabularResults.push({ key, success_count, failure_count })
                } else if (metricType === InsightType.TRENDS) {
                    const { key, count, exposure, absolute_exposure } = variantObj as TrendExperimentVariant
                    tabularResults.push({ key, count, exposure, absolute_exposure })
                }
            }
        }

        if (experiment.feature_flag?.filters.multivariate?.variants) {
            for (const { key } of experiment.feature_flag.filters.multivariate.variants) {
                if (tabularResults.find((variantObj) => variantObj.key === key)) {
                    continue
                }

                if (metricType === InsightType.FUNNELS) {
                    tabularResults.push({ key, success_count: null, failure_count: null })
                } else if (metricType === InsightType.TRENDS) {
                    tabularResults.push({ key, count: null, exposure: null, absolute_exposure: null })
                }
            }
        }

        return tabularResults
    }

/**
 * @deprecated
 * Use the experimentMathAggregationForTrends function from the experimentLogic instead.
 */
export const getExperimentMathAggregationForTrends = (
    experiment: Experiment
): PropertyMathType | CountPerActorMathType | undefined => {
    const query = experiment?.metrics?.[0] as ExperimentTrendsQuery
    if (!query) {
        return undefined
    }
    const entities = query.count_query?.series || []

    // Find out if we're using count per actor math aggregates averages per user
    const userMathValue = entities.filter((entity) =>
        Object.values(CountPerActorMathType).includes(entity?.math as CountPerActorMathType)
    )[0]?.math

    // alternatively, if we're using property math
    // remove 'sum' property math from the list of math types
    // since we can handle that as a regular case
    const targetValues = Object.values(PropertyMathType).filter((value) => value !== PropertyMathType.Sum)

    const propertyMathValue = entities.filter((entity) =>
        (targetValues as readonly PropertyMathType[]).includes(entity?.math as PropertyMathType)
    )[0]?.math

    return (userMathValue ?? propertyMathValue) as PropertyMathType | CountPerActorMathType | undefined
}

/**
 * @deprecated
 * Use the getIsPrimaryMetricSignificant function from the experimentLogic instead.
 */
export const getIsPrimaryMetricSignificant =
    (
        legacyPrimaryMetricsResults: (
            | CachedLegacyExperimentQueryResponse
            | CachedExperimentFunnelsQueryResponse
            | CachedExperimentTrendsQueryResponse
            | null
        )[],
        experiment: Experiment
    ) =>
    (metricUuid: string): boolean => {
        // Find metric index by UUID
        const index = experiment.metrics.findIndex((m) => m.uuid === metricUuid)
        if (index === -1) {
            return false
        }

        const result = legacyPrimaryMetricsResults?.[index]
        if (!result) {
            return false
        }

        return result.significant || false
    }

/**
 * @deprecated
 * Use the getIsSecondaryMetricSignificant function from the experimentLogic instead.
 */
export const getIsSecondaryMetricSignificant =
    (
        legacySecondaryMetricsResults: (
            | CachedLegacyExperimentQueryResponse
            | CachedExperimentFunnelsQueryResponse
            | CachedExperimentTrendsQueryResponse
            | null
        )[],
        experiment: Experiment
    ) =>
    (metricUuid: string): boolean => {
        // Find metric index by UUID
        const index = experiment.metrics_secondary.findIndex((m) => m.uuid === metricUuid)
        if (index === -1) {
            return false
        }

        const result = legacySecondaryMetricsResults?.[index]
        if (!result) {
            return false
        }

        return result.significant || false
    }

/**
 * @deprecated
 * Use the getSignificanceDetails function from the experimentLogic instead.
 */
export const getSignificanceDetails =
    (
        legacyPrimaryMetricsResults: (
            | CachedLegacyExperimentQueryResponse
            | CachedExperimentFunnelsQueryResponse
            | CachedExperimentTrendsQueryResponse
            | null
        )[],
        experiment: Experiment
    ) =>
    (metricUuid: string): string => {
        // Find metric index by UUID
        const index = experiment.metrics.findIndex((m) => m.uuid === metricUuid)
        if (index === -1) {
            return ''
        }

        const results = legacyPrimaryMetricsResults?.[index]
        return legacyGetSignificanceDetails(results)
    }
