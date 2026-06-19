import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'
import {
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
    isExperimentRetentionMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

const VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
const VARIANCE_SCALING_FACTOR_SUM = 0.25

// Manual calculator only supports these types (ratio/retention require full baseline data)
export type ManualCalculatorMetricType = 'funnel' | 'mean_count' | 'mean_sum_or_avg'

// Full calculator supports all metric types
export type CalculatorMetricType = ManualCalculatorMetricType | 'ratio' | 'retention'

/**
 * Calculate variance for manual calculator metric types.
 * Only supports funnel, mean_count, and mean_sum_or_avg since ratio/retention
 * require full baseline statistics from experiment results.
 */
export function calculateVariance(metricType: ManualCalculatorMetricType, baselineValue: number): number | null {
    switch (metricType) {
        case 'funnel':
            return null // variance embedded in p(1-p) formula
        case 'mean_count':
            return VARIANCE_SCALING_FACTOR_TOTAL_COUNT * baselineValue
        case 'mean_sum_or_avg':
            return VARIANCE_SCALING_FACTOR_SUM * baselineValue ** 2
    }
}

/**
 * Calculate variance from experiment results based on metric type.
 *
 * - For mean metrics (Count/Sum): Uses scaling factors based on metric type
 * - For funnel metrics: Returns null (variance is implicit in p(1-p))
 * - For ratio and retention metrics: Uses delta method with covariance
 *
 * Delta method for ratio R = M/D:
 * Var(R) ≈ Var(M)/D² + M²Var(D)/D⁴ - 2M*Cov(M,D)/D³
 */
export function calculateVarianceFromResults(
    baselineValue: number,
    metric: ExperimentMetric,
    baseline?: CachedNewExperimentQueryResponse['baseline']
): number | null {
    if (isExperimentMeanMetric(metric)) {
        if (metric.source.math === ExperimentMetricMathType.Sum) {
            return VARIANCE_SCALING_FACTOR_SUM * baselineValue ** 2
        }
        // Default to TotalCount for mean metrics (when math is undefined or TotalCount)
        return VARIANCE_SCALING_FACTOR_TOTAL_COUNT * baselineValue
    }

    if (isExperimentFunnelMetric(metric)) {
        // Funnel metrics don't need separate variance calculation
        // The variance is embedded in the formula: p(1-p)
        return null
    }

    if (isExperimentRatioMetric(metric) || isExperimentRetentionMetric(metric)) {
        // Both ratio and retention metrics use delta method variance
        // Retention: variance of (completions / starters)
        // Ratio: variance of (numerator / denominator)
        if (!baseline || !baseline.denominator_sum || baseline.denominator_sum === 0) {
            lemonToast.error('Ratio/retention metric missing denominator statistics')
            return null
        }

        const n = baseline.number_of_samples
        if (n === 0) {
            return null
        }

        // Calculate means for numerator (M) and denominator (D)
        const meanM = baseline.sum / n
        const meanD = baseline.denominator_sum / n

        // Calculate variances using the formula: Var(X) = E[X²] - E[X]²
        const varM = baseline.sum_squares / n - meanM ** 2
        const varD = (baseline.denominator_sum_squares || 0) / n - meanD ** 2

        // Calculate covariance: Cov(M,D) = E[MD] - E[M]E[D]
        const cov = (baseline.numerator_denominator_sum_product || 0) / n - meanM * meanD

        // Delta method variance formula for ratio R = M/D
        // Formula: Var(R) ≈ Var(M)/D² + M²Var(D)/D⁴ - 2M*Cov(M,D)/D³
        return varM / meanD ** 2 + (meanM ** 2 * varD) / meanD ** 4 - (2 * meanM * cov) / meanD ** 3
    }

    return null
}

/**
 * Calculate sample size for manual calculator metric types.
 * For ratio/retention metrics that require pre-calculated variance, use calculateSampleSizeWithVariance.
 */
export function calculateSampleSize(
    metricType: ManualCalculatorMetricType,
    baselineValue: number,
    mde: number,
    numberOfVariants: number
): number | null {
    if (mde === 0) {
        return null
    }

    const mdeDecimal = mde / 100
    const d = mdeDecimal * baselineValue

    if (d === 0) {
        return null
    }

    let sampleSizeFormula: number

    if (metricType === 'funnel') {
        // Binomial metric: N = (16 * p * (1 - p)) / d²
        sampleSizeFormula = (16 * baselineValue * (1 - baselineValue)) / d ** 2
    } else {
        // Count or Sum metric: N = (16 * variance) / d²
        const variance = calculateVariance(metricType, baselineValue)
        if (variance === null) {
            return null
        }
        sampleSizeFormula = (16 * variance) / d ** 2
    }

    return Math.ceil(sampleSizeFormula * numberOfVariants)
}

/**
 * Calculate sample size when variance is pre-calculated (for ratio/retention metrics).
 */
export function calculateSampleSizeWithVariance(
    metricType: CalculatorMetricType,
    baselineValue: number,
    mde: number,
    numberOfVariants: number,
    variance: number | null
): number | null {
    if (mde === 0) {
        return null
    }

    const mdeDecimal = mde / 100
    const d = mdeDecimal * baselineValue

    if (d === 0) {
        return null
    }

    let sampleSizeFormula: number

    if (metricType === 'funnel') {
        // Binomial metric: N = (16 * p * (1 - p)) / d²
        sampleSizeFormula = (16 * baselineValue * (1 - baselineValue)) / d ** 2
    } else {
        // Count, Sum, Ratio, or Retention: N = (16 * variance) / d²
        if (variance === null) {
            return null
        }
        sampleSizeFormula = (16 * variance) / d ** 2
    }

    return Math.ceil(sampleSizeFormula * numberOfVariants)
}

/**
 * Get the calculator metric type from an ExperimentMetric object.
 */
export function getCalculatorMetricType(metric: ExperimentMetric): CalculatorMetricType {
    if (isExperimentFunnelMetric(metric)) {
        return 'funnel'
    }
    if (isExperimentRatioMetric(metric)) {
        return 'ratio'
    }
    if (isExperimentRetentionMetric(metric)) {
        return 'retention'
    }
    if (isExperimentMeanMetric(metric) && metric.source.math === ExperimentMetricMathType.Sum) {
        return 'mean_sum_or_avg'
    }
    return 'mean_count'
}

// Returns: avg events/user (count), avg property value/user (sum), conversion rate (funnel), or ratio (ratio/retention)
export function calculateBaselineValue(
    baseline: CachedNewExperimentQueryResponse['baseline'],
    metric: ExperimentMetric
): number | null {
    if (baseline.number_of_samples === 0) {
        return null
    }

    if (isExperimentMeanMetric(metric)) {
        return baseline.sum / baseline.number_of_samples
    }

    if (isExperimentFunnelMetric(metric)) {
        const stepCounts = baseline.step_counts
        if (!stepCounts || stepCounts.length === 0) {
            // Fallback to sum / number_of_samples for funnels when step_counts is not available
            if (baseline.number_of_samples > 0) {
                return baseline.sum / baseline.number_of_samples
            }
            lemonToast.error('Funnel metric missing step_counts and sample data')
            return null
        }
        // For experiments, conversion rate is: (completed final step) / (total exposed)
        return baseline.number_of_samples > 0 ? stepCounts[stepCounts.length - 1] / baseline.number_of_samples : null
    }

    if (isExperimentRatioMetric(metric) || isExperimentRetentionMetric(metric)) {
        // Both ratio and retention metrics use denominator_sum for the baseline calculation
        // Retention: completions / starters
        // Ratio: numerator / denominator
        if (!baseline.denominator_sum || baseline.denominator_sum === 0) {
            return null
        }
        return baseline.sum / baseline.denominator_sum
    }

    return null
}

/**
 * Calculate recommended sample size from experiment metric and results.
 * Handles all metric types including ratio and retention.
 */
export function calculateRecommendedSampleSize(
    metric: ExperimentMetric,
    minimumDetectableEffect: number,
    baselineValue: number,
    numberOfVariants: number,
    baseline?: CachedNewExperimentQueryResponse['baseline']
): number | null {
    const metricType = getCalculatorMetricType(metric)

    // For ratio/retention, we need variance from full baseline data
    if (metricType === 'ratio' || metricType === 'retention') {
        const variance = calculateVarianceFromResults(baselineValue, metric, baseline)
        return calculateSampleSizeWithVariance(
            metricType,
            baselineValue,
            minimumDetectableEffect,
            numberOfVariants,
            variance
        )
    }

    // For funnel, mean_count, mean_sum_or_avg - use simple calculation
    return calculateSampleSize(metricType, baselineValue, minimumDetectableEffect, numberOfVariants)
}

export function calculateCurrentExposures(results: CachedNewExperimentQueryResponse | null): number | null {
    if (!results) {
        return null
    }

    const baselineCount = results.baseline.number_of_samples
    const variantCount = results.variant_results.reduce((sum, variant) => sum + variant.number_of_samples, 0)

    return baselineCount + variantCount
}

export function calculateDaysElapsed(startDate: string | null): number | null {
    if (!startDate) {
        return null
    }

    return dayjs().diff(dayjs(startDate), 'days', true) // fractional days
}

export function calculateExposureRate(currentExposures: number | null, daysElapsed: number | null): number | null {
    if (!currentExposures || !daysElapsed || daysElapsed < 0.1) {
        return null
    }

    return currentExposures / daysElapsed
}

export function calculateRemainingDays(
    recommendedSampleSize: number | null,
    currentExposures: number | null,
    exposureRate: number | null
): number | null {
    if (!recommendedSampleSize || !currentExposures || !exposureRate) {
        return null
    }

    const remainingSample = recommendedSampleSize - currentExposures

    if (remainingSample <= 0) {
        return 0
    }

    return remainingSample / exposureRate
}
