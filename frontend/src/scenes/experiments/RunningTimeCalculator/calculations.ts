import { dayjs } from 'lib/dayjs'

import type { CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'
import {
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
    isExperimentRetentionMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

import type { RunningTimeBaselineStatsApi } from 'products/experiments/frontend/generated/api.schemas'

// The sample-size and variance math lives in the backend running-time calculator
// (products/experiments/backend/running_time_calculator.py), reached via
// POST /experiments/calculate_running_time. This module keeps only the client-side
// helpers that classify a metric and read live experiment state to build that request.

// Manual calculator only supports these types (ratio/retention require full baseline data).
export type ManualCalculatorMetricType = 'funnel' | 'mean_count' | 'mean_sum_or_avg'

// Full calculator supports all metric types.
export type CalculatorMetricType = ManualCalculatorMetricType | 'ratio' | 'retention'

/**
 * Map an ExperimentMetric to the calculator metric type expected by the backend endpoint.
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

/**
 * Shape the raw baseline stats from experiment results into the backend request body.
 * The backend derives the baseline value and (for ratio/retention) the delta-method variance from these.
 */
export function baselineStatsFromResults(
    baseline: CachedNewExperimentQueryResponse['baseline']
): RunningTimeBaselineStatsApi {
    // Omit optional stats that are null for this metric type (e.g. step_counts on non-funnel
    // metrics, denominator_* on non-ratio metrics) — the serializer rejects explicit nulls,
    // and the backend already treats absent values as unset.
    return {
        number_of_samples: baseline.number_of_samples,
        sum: baseline.sum,
        sum_squares: baseline.sum_squares,
        denominator_sum: baseline.denominator_sum ?? undefined,
        denominator_sum_squares: baseline.denominator_sum_squares ?? undefined,
        numerator_denominator_sum_product: baseline.numerator_denominator_sum_product ?? undefined,
        step_counts: baseline.step_counts ?? undefined,
    }
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
