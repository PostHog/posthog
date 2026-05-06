import type { Series } from '../core/types'
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
            labelPosition: line.labelPosition ?? 'start',
            variant: 'goal',
            style: line.color ? { color: line.color } : undefined,
        }))
}
