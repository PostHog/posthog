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
    key: string
    kind: 'now' | 'week' | 'custom'
    // Since launch.
    days: number
    // So far for today, projected for the week marks, and the target sample for the custom row.
    exposures: number
    // The smallest relative change, as a percentage, that the exposures by then can detect.
    detectableEffect: number
    isTarget: boolean
}

export interface RunningTimeOutlook {
    // Since launch, to the row the user chose as the target.
    daysToTarget: number
    isOutOfReach: boolean
    // Today, the backend's next week marks and the custom row, by date.
    checkpoints: DetectableEffectCheckpoint[]
    // The smallest change detectable within four weeks from today, which the header shows for a target out of reach.
    reachableEffect: number
}

/**
 * Rounded up to three significant figures, because the exposures can't detect a smaller change than the exact value.
 * Set as the minimum detectable effect, the rounded value needs at most 2% fewer exposures than the row it came from.
 */
export function roundUpDetectableEffect(detectableEffect: number): number {
    if (!(detectableEffect > 0)) {
        return detectableEffect
    }
    const precision = 10 ** (2 - Math.floor(Math.log10(detectableEffect)))
    // Round before the ceiling, so that float noise doesn't turn an exact 30 into 30.1.
    return Math.ceil(Number((detectableEffect * precision).toFixed(6))) / precision
}

/**
 * The backend's projection of what the experiment can detect over time, as a fixed set of rows: today, the next week
 * marks, and a custom row for the effect that the slider sets. The slider moves the custom row, and "Use" chooses a row
 * as the target, so no interaction adds or removes a row. Every row sits where the projection reaches its exposures.
 */
export function buildRunningTimeOutlook({
    projection,
    currentSampleSize,
    savedEffect,
    savedSampleSize,
    defaultEffect,
    enteredEffect,
    selectedKey,
    minimumDetectableEffect,
}: {
    projection: RunningTimeOutlookApi | null
    currentSampleSize: number | null
    // The effect the backend sized its target for, and that target.
    savedEffect: number | null
    savedSampleSize: number | null
    defaultEffect: number
    // The last effect from the slider or the input, null until the user changes it.
    enteredEffect: number | null
    // The row the user chose with "Use", null when the custom row is the target.
    selectedKey: string | null
    minimumDetectableEffect: number
}): RunningTimeOutlook | null {
    if (!projection || currentSampleSize === null || !savedEffect || !savedSampleSize) {
        return null
    }
    const rate = projection.exposures_per_day
    const now: DetectableEffectCheckpoint = {
        key: 'now',
        kind: 'now',
        days: projection.days_since_launch,
        exposures: currentSampleSize,
        detectableEffect: projection.detectable_effect_now,
        isTarget: false,
    }
    const weeks = projection.upcoming_checkpoints.map(
        (checkpoint): DetectableEffectCheckpoint => ({
            key: `week-${checkpoint.weeks_since_launch}`,
            kind: 'week',
            days: checkpoint.weeks_since_launch * 7,
            exposures: Math.round(rate * checkpoint.weeks_since_launch * 7),
            detectableEffect: checkpoint.detectable_effect,
            isTarget: false,
        })
    )
    // A saved effect that today or a week mark shows came from that row's "Use", so that row is the target. The custom
    // row then starts at the default effect rather than repeat the row.
    const savedRow = [now, ...weeks].find(
        (checkpoint) => roundUpDetectableEffect(checkpoint.detectableEffect) === roundUpDetectableEffect(savedEffect)
    )
    const customEffect = enteredEffect ?? (savedRow ? defaultEffect : savedEffect)
    const customSampleSize = rescaleSampleSize(savedSampleSize, savedEffect, customEffect)
    if (!customSampleSize) {
        return null
    }
    const custom: DetectableEffectCheckpoint = {
        key: 'custom',
        kind: 'custom',
        days: customSampleSize / rate,
        exposures: customSampleSize,
        detectableEffect: customEffect,
        isTarget: false,
    }
    const rows = [now, ...weeks, custom]
    const targetKey = selectedKey ?? (enteredEffect === null && savedRow ? savedRow.key : custom.key)
    const target = rows.find((checkpoint) => checkpoint.key === targetKey) ?? custom

    return {
        daysToTarget: target.days,
        isOutOfReach: minimumDetectableEffect < projection.reachable_effect,
        checkpoints: rows
            .map((checkpoint) => (checkpoint === target ? { ...checkpoint, isTarget: true } : checkpoint))
            .sort((a, b) => a.days - b.days),
        reachableEffect: projection.reachable_effect,
    }
}

/**
 * Calendar days from today to a day since launch, at least one, so that the header and the table count alike.
 */
export function daysFromToday(startDate: string, daysSinceLaunch: number): number {
    const date = dayjs(startDate).add(daysSinceLaunch * 24, 'hour')
    return Math.max(1, date.startOf('day').diff(dayjs().startOf('day'), 'day'))
}

export function describeCheckpointDay(
    checkpoint: DetectableEffectCheckpoint,
    { startDate, currentSampleSize }: { startDate: string; currentSampleSize: number }
): string {
    if (checkpoint.kind === 'week') {
        return `week ${checkpoint.days / 7}`
    }
    if (checkpoint.kind === 'custom' && checkpoint.exposures > currentSampleSize) {
        const days = daysFromToday(startDate, checkpoint.days)
        return `in ${days.toLocaleString()} ${days === 1 ? 'day' : 'days'}`
    }
    // Calendar days, like the dates beside them, so that rows on one date show one day and the launch date is day 1.
    const launch = dayjs(startDate)
    const day =
        launch
            .add(checkpoint.days * 24, 'hour')
            .startOf('day')
            .diff(launch.startOf('day'), 'day') + 1
    return `day ${day.toLocaleString()}`
}

export function describeUseButton(checkpoint: DetectableEffectCheckpoint): {
    effect: number
    disabledReason?: string
    tooltip?: string
} {
    const effect =
        checkpoint.kind === 'custom'
            ? checkpoint.detectableEffect
            : roundUpDetectableEffect(checkpoint.detectableEffect)
    if (effect > MINIMUM_DETECTABLE_EFFECT_MAX) {
        return {
            effect,
            disabledReason: `The minimum detectable effect can be at most ${MINIMUM_DETECTABLE_EFFECT_MAX}%`,
        }
    }
    if (effect < MINIMUM_DETECTABLE_EFFECT_MIN) {
        return {
            effect,
            disabledReason: `The minimum detectable effect must be at least ${MINIMUM_DETECTABLE_EFFECT_MIN}%`,
        }
    }
    return { effect, tooltip: `Set ${effect.toLocaleString()}% as the minimum detectable effect` }
}

/**
 * Past the largest effect the settings accept, the exact value is too large to act on, so it shows as ">100%".
 */
export function formatDetectableEffect(detectableEffect: number): string {
    const effect = roundUpDetectableEffect(detectableEffect)
    return effect > MINIMUM_DETECTABLE_EFFECT_MAX
        ? `>${MINIMUM_DETECTABLE_EFFECT_MAX}%`
        : `${effect.toLocaleString(undefined, { maximumSignificantDigits: 3 })}%`
}
