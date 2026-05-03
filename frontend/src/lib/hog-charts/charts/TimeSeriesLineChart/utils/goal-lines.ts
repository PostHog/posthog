import type { Series } from '../../../core/types'
import type { ReferenceLineProps } from '../../../overlays/ReferenceLine'

/** Library-agnostic shape for a horizontal goal line. Adapters in product code
 *  (e.g. trends' SchemaGoalLine adapter) translate their persisted shape to this. */
export interface GoalLineConfig {
    /** Y-value at which to draw the line. */
    value: number
    /** Optional text label rendered alongside the line. */
    label?: string
    /** When `false`, suppress the label even if `label` is set. Defaults to `true`. */
    displayLabel?: boolean
    /** Color override for both the line stroke and label. */
    color?: string
    /** Anchor for the label. Defaults to `'start'`. */
    labelPosition?: 'start' | 'end'
    /** When explicitly `false`, hide the line if any series value already exceeds it
     *  (matches the trends "displayIfCrossed" semantics). Defaults to `true`. */
    displayIfCrossed?: boolean
}

/** Compute the max non-zero, non-NaN value across all visible series.
 *  Used for the `displayIfCrossed` filter in {@link buildGoalLineReferenceLines}. */
export function computeSeriesNonZeroMax(series: Series[]): number {
    let max = Number.NEGATIVE_INFINITY
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        for (const raw of s.data) {
            const value = Number(raw)
            // `!value` covers both 0 and NaN (since `!NaN === true`).
            if (!value) {
                continue
            }
            if (value > max) {
                max = value
            }
        }
    }
    return max === Number.NEGATIVE_INFINITY ? 0 : max
}

/** Map {@link GoalLineConfig}s to {@link ReferenceLineProps}, applying the
 *  `displayIfCrossed` filter so already-crossed targets are dropped. */
export function buildGoalLineReferenceLines(
    lines: GoalLineConfig[] | null | undefined,
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
