import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'

import {
    CachedExperimentFunnelsQueryResponse,
    CachedExperimentTrendsQueryResponse,
    CachedLegacyExperimentQueryResponse,
    ExperimentSignificanceCode,
    NodeKind,
    isExperimentFunnelMetric,
} from '~/queries/schema/schema-general'
import {
    CountPerActorMathType,
    FunnelExperimentVariant,
    FunnelStep,
    InsightType,
    PropertyMathType,
    TrendExperimentVariant,
    TrendResult,
} from '~/types'

// Type definitions
export type LegacyExperimentMetricResult =
    | CachedLegacyExperimentQueryResponse
    | CachedExperimentTrendsQueryResponse
    | CachedExperimentFunnelsQueryResponse
    | null

export type ExperimentVariant = FunnelExperimentVariant | TrendExperimentVariant

export interface DeltaResult {
    delta: number
    deltaPercent: number
    isPositive: boolean
}

export interface VariantCalculationResult {
    conversionRate: number | null
    count: number | null
    exposure: number | null
    mean: number | null
    credibleInterval: [number, number] | null
    delta: DeltaResult | null
}

/**
 * Calculate conversion rate for a specific variant in experiment results
 */
export function conversionRateForVariant(
    metricResult: LegacyExperimentMetricResult,
    variantKey: string
): number | null {
    if (!metricResult) {
        return null
    }

    if (metricResult.kind === NodeKind.ExperimentQuery && isExperimentFunnelMetric(metricResult.metric)) {
        const variants = metricResult.variants as FunnelExperimentVariant[]
        const variantResults = variants.find((variant) => variant.key === variantKey)

        if (!variantResults) {
            return null
        }
        return (variantResults.success_count / (variantResults.success_count + variantResults.failure_count)) * 100
    } else if (metricResult.kind === NodeKind.ExperimentFunnelsQuery && metricResult.insight) {
        const variantResults = (metricResult.insight as FunnelStep[][]).find((variantFunnel: FunnelStep[]) => {
            const breakdownValue = variantFunnel[0]?.breakdown_value
            return Array.isArray(breakdownValue) && breakdownValue[0] === variantKey
        })

        if (!variantResults) {
            return null
        }

        return (variantResults[variantResults.length - 1].count / variantResults[0].count) * 100
    }

    return null
}

/**
 * Get exposure count data for a specific variant
 */
export function exposureCountDataForVariant(
    metricResult: LegacyExperimentMetricResult,
    variant: string
): number | null {
    if (!metricResult || !metricResult.variants) {
        return null
    }

    if ('kind' in metricResult && metricResult.kind === NodeKind.ExperimentQuery) {
        const variantResults = (metricResult.variants as Array<{ key: string; exposure?: number }>).find(
            (variantData) => variantData.key === variant
        )
        return variantResults?.exposure ?? null
    }

    const variantResults = (metricResult.variants as TrendExperimentVariant[]).find(
        (variantTrend: TrendExperimentVariant) => variantTrend.key === variant
    )
    if (!variantResults || !variantResults.absolute_exposure) {
        return null
    }

    return variantResults.absolute_exposure
}

/**
 * Get count data for a specific variant with optional math aggregation
 */
export function countDataForVariant(
    metricResult: LegacyExperimentMetricResult,
    variant: string,
    type: 'primary' | 'secondary' = 'primary',
    experimentMathAggregation?: PropertyMathType | CountPerActorMathType
): number | null {
    if (!metricResult) {
        return null
    }

    if ('kind' in metricResult && metricResult.kind === NodeKind.ExperimentQuery) {
        const variantResults = (metricResult.variants as Array<{ key: string } & Record<string, any>>).find(
            (variantData) => variantData.key === variant
        )
        // NOTE: Unfortunately, there does not seem to be a better way at the moment to figure out which type it is.
        // Something we can improve later when we replace the ExperimentVariantTrendsBaseStats with a new type / interface.
        if (variantResults && 'success_count' in variantResults) {
            return variantResults.success_count + variantResults.failure_count
        } else if (variantResults && 'count' in variantResults) {
            return variantResults.count
        }
        return null
    }

    const usingMathAggregationType = type === 'primary' ? experimentMathAggregation : false
    if (!metricResult.insight) {
        return null
    }
    const variantResults = (metricResult.insight as TrendResult[]).find(
        (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
    )
    if (!variantResults) {
        return null
    }

    let result = variantResults.count

    if (usingMathAggregationType) {
        // TODO: Aggregate end result appropriately for nth percentile
        if (
            [
                CountPerActorMathType.Average,
                CountPerActorMathType.Median,
                PropertyMathType.Average,
                PropertyMathType.Median,
            ].includes(usingMathAggregationType)
        ) {
            result = variantResults.count / variantResults.data.length
        } else if ([CountPerActorMathType.Maximum, PropertyMathType.Maximum].includes(usingMathAggregationType)) {
            result = Math.max(...variantResults.data)
        } else if ([CountPerActorMathType.Minimum, PropertyMathType.Minimum].includes(usingMathAggregationType)) {
            result = Math.min(...variantResults.data)
        }
    }

    return result
}

/**
 * Calculate credible interval for a variant as percentage difference from control
 */
export function credibleIntervalForVariant(
    metricResult: LegacyExperimentMetricResult,
    variantKey: string,
    metricType: InsightType
): [number, number] | null {
    const credibleInterval = metricResult?.credible_intervals?.[variantKey]
    if (!credibleInterval) {
        return null
    }

    if (metricType === InsightType.FUNNELS) {
        const controlVariant = (metricResult.variants as FunnelExperimentVariant[]).find(
            ({ key }) => key === 'control'
        ) as FunnelExperimentVariant
        const controlConversionRate =
            controlVariant.success_count / (controlVariant.success_count + controlVariant.failure_count)

        if (!controlConversionRate) {
            return null
        }

        // Calculate the percentage difference between the credible interval bounds of the variant and the control's conversion rate.
        // This represents the range in which the true percentage change relative to the control is likely to fall.
        const lowerBound = ((credibleInterval[0] - controlConversionRate) / controlConversionRate) * 100
        const upperBound = ((credibleInterval[1] - controlConversionRate) / controlConversionRate) * 100
        return [lowerBound, upperBound]
    }

    const controlVariant = (metricResult.variants as TrendExperimentVariant[]).find(
        ({ key }) => key === 'control'
    ) as TrendExperimentVariant

    const controlMean = controlVariant.count / controlVariant.absolute_exposure
    if (!controlMean) {
        return null
    }

    // Calculate the percentage difference between the credible interval bounds of the variant and the control's mean.
    // This represents the range in which the true percentage change relative to the control is likely to fall.
    const relativeLowerBound = ((credibleInterval[0] - controlMean) / controlMean) * 100
    const relativeUpperBound = ((credibleInterval[1] - controlMean) / controlMean) * 100
    return [relativeLowerBound, relativeUpperBound]
}

/**
 * Get the index for a variant in experiment results (for UI display order)
 */
export function getIndexForVariant(
    metricResult: LegacyExperimentMetricResult,
    variant: string,
    metricType: InsightType
): number | null {
    // Ensures we get the right index from results, so the UI can
    // display the right colour for the variant
    if (!metricResult || !metricResult.insight) {
        return null
    }

    let index = -1
    if (metricType === InsightType.FUNNELS) {
        // Funnel Insight is displayed in order of decreasing count
        index = (Array.isArray(metricResult.insight) ? [...metricResult.insight] : [])
            .sort((a, b) => {
                const aCount = (a && Array.isArray(a) && a[0]?.count) || 0
                const bCount = (b && Array.isArray(b) && b[0]?.count) || 0
                return bCount - aCount
            })
            .findIndex((variantFunnel) => {
                if (!Array.isArray(variantFunnel) || !variantFunnel[0]?.breakdown_value) {
                    return false
                }
                const breakdownValue = variantFunnel[0].breakdown_value
                return Array.isArray(breakdownValue) && breakdownValue[0] === variant
            })
    } else {
        index = (metricResult.insight as TrendResult[]).findIndex(
            (variantTrend: TrendResult) => variantTrend.breakdown_value === variant
        )
    }
    const result = index === -1 ? null : index

    if (result !== null && metricType === InsightType.FUNNELS) {
        return result + 1
    }
    return result
}

/**
 * Get the variant with the highest win probability
 */
export function getHighestProbabilityVariant(results: LegacyExperimentMetricResult): string | undefined {
    if (results && results.probability) {
        const maxValue = Math.max(...Object.values(results.probability))
        return Object.keys(results.probability).find(
            (key) => Math.abs(results.probability[key] - maxValue) < Number.EPSILON
        )
    }
}

/**
 * Calculate minimum sample size per variant for a given conversion rate and MDE
 */
export function minimumSampleSizePerVariant(mde: number, conversionRate: number): number {
    // Using the rule of thumb: sampleSize = 16 * sigma^2 / (mde^2)
    // refer https://en.wikipedia.org/wiki/Sample_size_determination with default beta and alpha
    // The results are same as: https://www.evanmiller.org/ab-testing/sample-size.html
    // and also: https://marketing.dynamicyield.com/ab-test-duration-calculator/
    if (!mde) {
        return 0
    }

    return Math.ceil((1600 * conversionRate * (1 - conversionRate / 100)) / (mde * mde))
}

/**
 * Calculate recommended exposure for count data based on MDE
 */
export function recommendedExposureForCountData(mde: number, baseCountData: number): number {
    // http://www.columbia.edu/~cjd11/charles_dimaggio/DIRE/styled-4/code-12/
    if (!mde) {
        return 0
    }

    const minCountData = (baseCountData * mde) / 100
    const lambda1 = baseCountData
    const lambda2 = minCountData + baseCountData

    // This is exposure in units of days
    return parseFloat(
        (
            4 /
            Math.pow(
                Math.sqrt(lambda1 / EXPERIMENT_DEFAULT_DURATION) - Math.sqrt(lambda2 / EXPERIMENT_DEFAULT_DURATION),
                2
            )
        ).toFixed(1)
    )
}

/**
 * Calculate expected running time for an experiment
 */
export function expectedRunningTime(
    entrants: number,
    sampleSize: number,
    duration: number = EXPERIMENT_DEFAULT_DURATION
): number {
    // recommended people / (actual people / day) = expected days
    return parseFloat((sampleSize / (entrants / duration)).toFixed(1))
}

/**
 * Calculate delta (percentage change) between a variant and control
 */
export function calculateDelta(
    metricResult: LegacyExperimentMetricResult,
    variantKey: string,
    metricType: InsightType
): DeltaResult | null {
    if (!metricResult || variantKey === 'control') {
        return null
    }

    let delta = 0

    if (metricType === InsightType.TRENDS) {
        const controlVariant = (metricResult.variants as any[]).find((v: any) => v.key === 'control')
        const variantData = (metricResult.variants as any[]).find((v: any) => v.key === variantKey)

        if (
            !variantData?.count ||
            !variantData?.absolute_exposure ||
            !controlVariant?.count ||
            !controlVariant?.absolute_exposure
        ) {
            return null
        }

        const controlMean = controlVariant.count / controlVariant.absolute_exposure
        const variantMean = variantData.count / variantData.absolute_exposure
        delta = (variantMean - controlMean) / controlMean
    } else {
        const variantRate = conversionRateForVariant(metricResult, variantKey)
        const controlRate = conversionRateForVariant(metricResult, 'control')

        if (!variantRate || !controlRate) {
            return null
        }

        delta = (variantRate - controlRate) / controlRate
    }

    return {
        delta,
        deltaPercent: delta * 100,
        isPositive: delta > 0,
    }
}

/**
 * Get comprehensive calculation result for a variant
 */
export function getVariantCalculationResult(
    metricResult: LegacyExperimentMetricResult,
    variantKey: string,
    metricType: InsightType,
    experimentMathAggregation?: PropertyMathType | CountPerActorMathType
): VariantCalculationResult {
    const conversionRate = conversionRateForVariant(metricResult, variantKey)
    const count = countDataForVariant(metricResult, variantKey, 'primary', experimentMathAggregation)
    const exposure = exposureCountDataForVariant(metricResult, variantKey)
    const credibleInterval = credibleIntervalForVariant(metricResult, variantKey, metricType)
    const delta = calculateDelta(metricResult, variantKey, metricType)

    // Calculate mean for trends
    let mean: number | null = null
    if (metricType === InsightType.TRENDS && count !== null && exposure !== null && exposure > 0) {
        mean = count / exposure
    }

    return {
        conversionRate,
        count,
        exposure,
        mean,
        credibleInterval,
        delta,
    }
}

/**
 * Generate significance details text based on experiment results
 */
export function getSignificanceDetails(metricResult: LegacyExperimentMetricResult): string {
    if (!metricResult) {
        return ''
    }

    if (metricResult.significance_code === ExperimentSignificanceCode.HighLoss) {
        return `This is because the expected loss in conversion is greater than 1% (current value is ${(
            (metricResult as CachedExperimentFunnelsQueryResponse)?.expected_loss || 0
        )?.toFixed(2)}%).`
    }

    if (metricResult.significance_code === ExperimentSignificanceCode.HighPValue) {
        return `This is because the p value is greater than 0.05 (current value is ${
            (metricResult as CachedExperimentTrendsQueryResponse)?.p_value?.toFixed(3) || 1
        }).`
    }

    if (metricResult.significance_code === ExperimentSignificanceCode.LowWinProbability) {
        return 'This is because no variant (control or test) has a win probability higher than 90%.'
    }

    if (metricResult.significance_code === ExperimentSignificanceCode.NotEnoughExposure) {
        return 'This is because we need at least 100 people per variant to declare significance.'
    }

    return ''
}
