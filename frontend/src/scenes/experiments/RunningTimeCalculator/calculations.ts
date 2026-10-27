import { dayjs } from 'lib/dayjs'

import type { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'

import type { RunningTimeOutlookApi } from 'products/experiments/frontend/generated/api.schemas'

// The target sample and its outlook live in the backend (products/experiments/backend/running_time_target.py), reached
// via GET /experiments/:id/running_time_target, and the manual preview's math via POST
// /experiments/calculate_running_time. This module keeps the helpers that read live experiment state, rescale the target
// for an effect being edited, and place that target on the backend's outlook.

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

// The minimum detectable effects, as a percentage, that the running time settings accept.
export const MINIMUM_DETECTABLE_EFFECT_MIN = 1
export const MINIMUM_DETECTABLE_EFFECT_MAX = 100

/**
 * The target sample for another minimum detectable effect, by the rule the target endpoint documents: the variances come
 * from the results, so the sample scales with 1 / effect². The settings rescale locally, which lets every value of the
 * slider show its estimate at once, without a request.
 */
export function rescaleSampleSize(sampleSize: number, fromEffect: number, toEffect: number): number | null {
    if (!(sampleSize > 0) || !(fromEffect > 0) || !(toEffect > 0)) {
        return null
    }
    // Round before the ceiling, as the backend does, so that float noise doesn't turn an exact 3,200 into 3,201.
    return Math.ceil(Number((sampleSize * (fromEffect / toEffect) ** 2).toFixed(6)))
}

export interface DetectableEffectCheckpoint {
    kind: 'now' | 'week' | 'target'
    // Since launch.
    days: number
    // The smallest relative change, as a percentage, that the exposures by then can detect.
    detectableEffect: number
}

export interface RunningTimeOutlook {
    // Since launch, at the exposure rate so far.
    daysToTarget: number
    isOutOfReach: boolean
    // Today, the backend's next week marks and the target, by date. Only the target moves with the effect.
    checkpoints: DetectableEffectCheckpoint[]
    // The smallest change detectable within four weeks from today, which the header shows for a target out of reach.
    reachableEffect: number
}

/**
 * The backend's projection of what the experiment can detect over time, with the target for the effect on hand placed
 * on it. The target sits where the projection reaches its sample, so it shares the origin of the week marks.
 */
export function buildRunningTimeOutlook({
    projection,
    targetSampleSize,
    minimumDetectableEffect,
}: {
    projection: RunningTimeOutlookApi | null
    targetSampleSize: number | null
    minimumDetectableEffect: number
}): RunningTimeOutlook | null {
    if (!projection || !targetSampleSize || targetSampleSize <= 0) {
        return null
    }
    const { days_since_launch: elapsed, exposures_per_day: rate } = projection
    const daysToTarget = targetSampleSize / rate
    const target: DetectableEffectCheckpoint = {
        kind: 'target',
        days: daysToTarget,
        detectableEffect: minimumDetectableEffect,
    }
    const weeks = projection.upcoming_checkpoints.map(
        (checkpoint): DetectableEffectCheckpoint => ({
            kind: 'week',
            days: checkpoint.weeks_since_launch * 7,
            detectableEffect: checkpoint.detectable_effect,
        })
    )

    return {
        daysToTarget,
        isOutOfReach: minimumDetectableEffect < projection.reachable_effect,
        checkpoints: [
            { kind: 'now' as const, days: elapsed, detectableEffect: projection.detectable_effect_now },
            ...weeks,
            target,
        ].sort((a, b) => a.days - b.days),
        reachableEffect: projection.reachable_effect,
    }
}

/**
 * Rounded up, because the exposures can't detect a smaller change than the exact value. Set as the minimum detectable
 * effect, the rounded value puts the target on or before the checkpoint it came from.
 */
export function roundUpDetectableEffect(detectableEffect: number): number {
    const precision = detectableEffect < 10 ? 10 : 1
    // Take off float noise first, so that an exact 30 stays 30.
    return Math.ceil(detectableEffect * precision - 1e-9) / precision
}

export function formatDetectableEffect(detectableEffect: number): string {
    return `${roundUpDetectableEffect(detectableEffect).toLocaleString()}%`
}
