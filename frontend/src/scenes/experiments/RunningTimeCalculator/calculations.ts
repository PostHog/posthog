import { dayjs } from 'lib/dayjs'

import type { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'

// The target sample lives in the backend (products/experiments/backend/running_time_target.py), reached via
// GET /experiments/:id/running_time_target, and the manual preview's math via POST
// /experiments/calculate_running_time. This module keeps only the client-side helpers that read live experiment state.

// Manual calculator only supports these types (ratio/retention require full baseline data).
export type ManualCalculatorMetricType = 'funnel' | 'mean_count' | 'mean_sum_or_avg'

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
