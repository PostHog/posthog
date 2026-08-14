import type { Series, ValueDomain } from '../core/types'
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

/** Combine a consumer-set {@link ValueDomain} with the goal-line stretch, field by field, so a
 *  capped axis still stretches to reach an off-scale goal line. `a` wins a contested bound. A
 *  consumer pinning both ends still overrides the goal lines, but that is settled when the domain
 *  resolves and drops `include`, not here. */
export function mergeValueDomains(a: ValueDomain | undefined, b: ValueDomain | undefined): ValueDomain | undefined {
    if (!a || !b) {
        return a ?? b
    }
    const include = [...(a.include ?? []), ...(b.include ?? [])]
    return {
        include: include.length > 0 ? include : undefined,
        min: a.min ?? b.min,
        max: a.max ?? b.max,
    }
}
