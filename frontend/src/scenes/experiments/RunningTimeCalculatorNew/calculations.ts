/**
 * Self-contained utility functions for the new running time calculator.
 *
 */
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'
import { isExperimentFunnelMetric, isExperimentMeanMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'
import { ExperimentMetricMathType } from '~/types'

// Variance scaling factors for estimating variance from mean
const VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
const VARIANCE_SCALING_FACTOR_SUM = 0.25

/**
 * Extract the baseline value from experiment results based on metric type.
 * Returns the control group's performance metric:
 * - For count metrics: average events per user
 * - For sum metrics: average property value per user
 * - For funnel metrics: conversion rate
 */
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

    lemonToast.error(`Unknown metric type: ${metric.metric_type}`)
    return null
}

/**
 * Calculate variance from experiment results
 */
export function calculateVarianceFromResults(baselineValue: number, metric: ExperimentMetric): number | null {
    if (isExperimentMeanMetric(metric)) {
        if (metric.source.math === ExperimentMetricMathType.Sum) {
            const averagePropertyValuePerUser = baselineValue
            return VARIANCE_SCALING_FACTOR_SUM * averagePropertyValuePerUser ** 2
        }

        // Default to TotalCount for mean metrics (when math is undefined or TotalCount)
        const averageEventsPerUser = baselineValue
        return VARIANCE_SCALING_FACTOR_TOTAL_COUNT * averageEventsPerUser
    }

    if (isExperimentFunnelMetric(metric)) {
        // Funnel metrics don't need separate variance calculation
        // The variance is embedded in the formula: p(1-p)
        return null
    }

    lemonToast.error(`Unknown metric type: ${metric.metric_type}`)
    return null
}

/**
 * Calculate the recommended sample size needed for the experiment.
 *
 * This simplified version is designed for the new calculator that extracts metrics
 * from actual experiment results. The `baselineValue` parameter represents different things
 * depending on the metric type:
 * - For Sum metrics: average property value per user
 * - For Count metrics: average events per user
 * - For Funnel metrics: conversion rate
 */
export function calculateRecommendedSampleSize(
    metric: ExperimentMetric,
    minimumDetectableEffect: number,
    baselineValue: number,
    variance: number | null, // null for funnel metrics
    numberOfVariants: number
): number | null {
    const minimumDetectableEffectDecimal = minimumDetectableEffect / 100

    if (minimumDetectableEffectDecimal === 0) {
        lemonToast.error('Minimum detectable effect cannot be 0')
        return null
    }

    let d // Represents the absolute effect size (difference we want to detect)
    let sampleSizeFormula

    if (isExperimentMeanMetric(metric) && metric.source.math === ExperimentMetricMathType.Sum) {
        /**
         * Continuous property metric:
         *
         * - `averagePropertyValuePerUser` is the average value of the measured property per user (e.g., revenue per user).
         * - MDE is applied as a percentage of this mean to compute `d`.
         *
         * Formula:
         *
         * d = MDE * averagePropertyValuePerUser
         */
        const averagePropertyValuePerUser = baselineValue
        d = minimumDetectableEffectDecimal * averagePropertyValuePerUser

        /**
         * Sample Size Formula for Continuous metrics:
         *
         * N = (16 * variance) / d^2
         *
         * Where:
         * - `variance` is the estimated variance of the continuous property.
         * - The formula is identical to the Count metric case.
         */
        if (variance === null) {
            lemonToast.error('Mean metric (Sum) requires variance, but got null')
            return null
        }
        sampleSizeFormula = (16 * variance) / d ** 2
    } else if (isExperimentMeanMetric(metric)) {
        /**
         * Count Per User Metric (default for mean metrics when *math* is undefined or TotalCount):
         * - `averageEventsPerUser` is the average number of events per user (e.g., clicks per user).
         * - MDE is applied as a percentage of this average to compute `d`.
         *
         * Formula:
         * d = MDE * averageEventsPerUser
         */
        const averageEventsPerUser = baselineValue
        d = minimumDetectableEffectDecimal * averageEventsPerUser

        /**
         * Sample size formula:
         *
         * N = (16 * variance) / d^2
         *
         * Where:
         * - `16` comes from statistical power analysis:
         *    - Based on a 95% confidence level (Z_alpha/2 = 1.96) and 80% power (Z_beta = 0.84),
         *      the combined squared Z-scores yield approximately 16.
         * - `variance` is the estimated variance of the event count per user.
         * - `d` is the absolute effect size (MDE * averageEventsPerUser).
         */
        if (variance === null) {
            lemonToast.error('Mean metric (TotalCount) requires variance, but got null')
            return null
        }
        sampleSizeFormula = (16 * variance) / d ** 2
    } else if (isExperimentFunnelMetric(metric)) {
        /**
         * Binomial metric (conversion rate):
         *
         * - `conversionRate` is the baseline conversion rate (probability of success).
         * - MDE is applied as an absolute percentage change.
         *
         * Formula:
         *
         * d = MDE * conversionRate
         */
        const conversionRate = baselineValue
        d = minimumDetectableEffectDecimal * conversionRate

        /**
         * Sample size formula:
         *
         * N = (16 * p * (1 - p)) / d^2
         *
         * Where:
         * - `p` is the conversion rate (baseline success probability).
         * - `d` is the absolute MDE (e.g., detecting a 5% increase means `d = 0.05`).
         * - The variance is inherent in `p(1 - p)`, which represents binomial variance.
         */
        sampleSizeFormula = (16 * conversionRate * (1 - conversionRate)) / d ** 2
    } else {
        lemonToast.error(`Unknown metric type: ${metric.metric_type}`)
        return null
    }

    return Math.ceil(sampleSizeFormula * numberOfVariants)
}

/**
 * Calculate total current exposures across all variants
 */
export function calculateCurrentExposures(results: CachedNewExperimentQueryResponse | null): number | null {
    if (!results) {
        return null
    }

    const baselineCount = results.baseline.number_of_samples
    const variantCount = results.variant_results.reduce((sum, variant) => sum + variant.number_of_samples, 0)

    return baselineCount + variantCount
}

/**
 * Calculate days elapsed since experiment started
 */
export function calculateDaysElapsed(startDate: string | null): number | null {
    if (!startDate) {
        return null
    }

    return dayjs().diff(dayjs(startDate), 'days', true) // fractional days
}

/**
 * Calculate exposure rate (exposures per day)
 */
export function calculateExposureRate(currentExposures: number | null, daysElapsed: number | null): number | null {
    if (!currentExposures || !daysElapsed || daysElapsed < 0.1) {
        return null
    }

    return currentExposures / daysElapsed
}

/**
 * Calculate estimated remaining days to reach recommended sample size
 */
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

/**
 * Calculate all experiment time estimates from validated metric and experiment data.
 * Caller must ensure metric, result.baseline, and experiment.start_date are present.
 */
export function calculateExperimentTimeEstimate(
    metric: ExperimentMetric,
    result: CachedNewExperimentQueryResponse,
    experiment: Experiment,
    minimumDetectableEffect: number
): {
    currentExposures: number | null
    recommendedSampleSize: number | null
    exposureRate: number | null
    estimatedRemainingDays: number | null
} {
    const baselineValue = calculateBaselineValue(result.baseline, metric)
    if (baselineValue === null) {
        return { currentExposures: null, recommendedSampleSize: null, exposureRate: null, estimatedRemainingDays: null }
    }

    const variance = calculateVarianceFromResults(baselineValue, metric)
    const numberOfVariants = experiment.feature_flag?.filters.multivariate?.variants.length ?? 2

    const recommendedSampleSize = calculateRecommendedSampleSize(
        metric,
        minimumDetectableEffect,
        baselineValue,
        variance,
        numberOfVariants
    )

    const currentExposures = calculateCurrentExposures(result)
    const daysElapsed = calculateDaysElapsed(experiment.start_date!)
    const exposureRate = calculateExposureRate(currentExposures, daysElapsed)
    const estimatedRemainingDays = calculateRemainingDays(recommendedSampleSize, currentExposures, exposureRate)

    return { currentExposures, recommendedSampleSize, exposureRate, estimatedRemainingDays }
}
