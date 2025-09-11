import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { isExperimentFunnelMetric, isExperimentMeanMetric } from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

import { ConversionRateInputType } from './runningTimeCalculatorLogic'

export const VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
export const VARIANCE_SCALING_FACTOR_SUM = 0.25

/**
 * Calculate the variance of the metric.
 */
export const calculateVariance = (
    metric: ExperimentMetric,
    averageEventsPerUser: number,
    averagePropertyValuePerUser: number
): number | null => {
    if (!metric) {
        return null
    }

    if (isExperimentMeanMetric(metric) && metric.source.math === ExperimentMetricMathType.TotalCount) {
        return VARIANCE_SCALING_FACTOR_TOTAL_COUNT * averageEventsPerUser
    }

    if (isExperimentMeanMetric(metric) && metric.source.math === ExperimentMetricMathType.Sum) {
        return VARIANCE_SCALING_FACTOR_SUM * averagePropertyValuePerUser ** 2
    }

    return null
}

export const calculateRecommendedSampleSize = (
    metric: ExperimentMetric,
    minimumDetectableEffect: number,
    variance: number,
    averageEventsPerUser: number,
    averagePropertyValuePerUser: number,
    automaticConversionRateDecimal: number,
    manualConversionRate: number,
    conversionRateInputType: ConversionRateInputType,
    numberOfVariants: number
): number | null => {
    if (!metric) {
        return null
    }

    const minimumDetectableEffectDecimal = minimumDetectableEffect / 100

    let d // Represents the absolute effect size (difference we want to detect)
    let sampleSizeFormula // The correct sample size formula for each metric type

    if (isExperimentMeanMetric(metric) && metric.source.math === ExperimentMetricMathType.TotalCount) {
        /**
         * Count Per User Metric:
         * - "mean" is the average number of events per user (e.g., clicks per user).
         * - MDE is applied as a percentage of this mean to compute `d`.
         *
         * Formula:
         * d = MDE * averageEventsPerUser
         */
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
         * - `d` is the absolute effect size (MDE * mean).
         */
        sampleSizeFormula = (16 * variance) / d ** 2
    } else if (isExperimentMeanMetric(metric) && metric.source.math === ExperimentMetricMathType.Sum) {
        /**
         * Continuous property metric:
         *
         * - "mean" is the average value of the measured property per user (e.g., revenue per user).
         * - MDE is applied as a percentage of this mean to compute `d`.
         *
         * Formula:
         *
         * d = MDE * averagePropertyValuePerUser
         */
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
        sampleSizeFormula = (16 * variance) / d ** 2
    } else if (isExperimentFunnelMetric(metric)) {
        const manualConversionRateDecimal = manualConversionRate / 100
        const conversionRate =
            conversionRateInputType === ConversionRateInputType.MANUAL
                ? manualConversionRateDecimal
                : automaticConversionRateDecimal

        /**
         * Binomial metric (conversion rate):
         *
         * - Here, "mean" does not exist in the same way as for count/continuous metrics.
         * - Instead, we use `p`, the baseline conversion rate (historical probability of success).
         * - MDE is applied as an absolute percentage change to `p`.
         *
         * Formula:
         *
         * d = MDE * conversionRate
         */
        d = minimumDetectableEffectDecimal * conversionRate

        /**
         * Sample size formula:
         *
         * N = (16 * p * (1 - p)) / d^2
         *
         * Where:
         * - `p` is the historical conversion rate (baseline success probability).
         * - `d` is the absolute MDE (e.g., detecting a 5% increase means `d = 0.05`).
         * - The variance is inherent in `p(1 - p)`, which represents binomial variance.
         */
        if (conversionRate !== null) {
            sampleSizeFormula = (16 * conversionRate * (1 - conversionRate)) / d ** 2
        } else {
            return null
        }
    }

    if (!d || !sampleSizeFormula) {
        return null
    }

    return sampleSizeFormula * numberOfVariants
}
