import type { Series, ValueDomain, ValueDomainAdjustments } from '../core/types'
import type { ReferenceLineProps } from '../overlays/ReferenceLine'

export interface GoalLineConfig {
    value: number
    label?: string
    displayLabel?: boolean
    color?: string
    labelPosition?: 'start' | 'end'
    displayIfCrossed?: boolean
}

export function computeSeriesNonZeroMax(series: Series[]): number {
    let max = Number.NEGATIVE_INFINITY
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        for (const raw of s.data) {
            const value = Number(raw)
            if (value === 0 || !Number.isFinite(value)) {
                continue
            }
            if (value > max) {
                max = value
            }
        }
    }
    return max === Number.NEGATIVE_INFINITY ? 0 : max
}

export function buildGoalLineReferenceLines(
    lines: readonly GoalLineConfig[] | null | undefined,
    series: Series[]
): ReferenceLineProps[] {
    if (!lines?.length) {
        return []
    }
    const seriesNonZeroMax = computeSeriesNonZeroMax(series)
    return lines
        .filter((line) => line.displayIfCrossed !== false || line.value >= seriesNonZeroMax)
        .map((line) => ({
            value: line.value,
            orientation: 'horizontal',
            label: line.displayLabel === false ? undefined : line.label,
            // Match the UI control and legacy chart.js, which both default an unset position to 'end'.
            labelPosition: line.labelPosition ?? 'end',
            variant: 'goal',
            style: line.color ? { color: line.color } : undefined,
        }))
}

/** Numeric values of a set of reference lines as a {@link ValueDomain}, so the chart's value axis
 *  stretches to keep off-scale goal lines on-plot. Returns `undefined` when there's nothing to add. */
export function goalLineValueDomain(referenceLines: readonly ReferenceLineProps[]): ValueDomain | undefined {
    const values = referenceLines.map((line) => line.value).filter((v): v is number => typeof v === 'number')
    return values.length > 0 ? { include: values } : undefined
}

/** Combine a consumer-set {@link ValueDomain} with the goal-line stretch. A pinned tuple wins
 *  outright — the consumer fixed the axis, so nothing may stretch or clamp it — while two sets of
 *  adjustments merge field by field, so an off-scale goal line still widens an axis the user has
 *  also capped.
 *
 *  Discriminates on `Array.isArray`, not on a key being present: every adjustment is optional, so
 *  `{ min: 40 }` would read as a pinned tuple under a key-presence check and drop the goal lines. */
export function mergeValueDomains(a: ValueDomain | undefined, b: ValueDomain | undefined): ValueDomain | undefined {
    if (!a || !b) {
        return a ?? b
    }
    if (Array.isArray(a)) {
        return a
    }
    if (Array.isArray(b)) {
        return b
    }
    const left = a as ValueDomainAdjustments
    const right = b as ValueDomainAdjustments
    const include = [...(left.include ?? []), ...(right.include ?? [])]
    return {
        include: include.length > 0 ? include : undefined,
        min: left.min ?? right.min,
        max: left.max ?? right.max,
    }
}
