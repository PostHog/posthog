import type { Series } from 'lib/hog-charts'
import type { ReferenceLineProps } from 'lib/hog-charts/overlays/ReferenceLine'

import type { GoalLine as SchemaGoalLine } from '~/queries/schema/schema-general'

/** Compute the max non-zero, non-NaN value across all series. Used for the
 *  `displayIfCrossed` filter below. Matches the Chart.js LineGraph behavior. */
export function computeSeriesNonZeroMax(series: Series[]): number {
    let max = Number.NEGATIVE_INFINITY
    for (const s of series) {
        if (s.hidden) {
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

/** Map persisted {@link SchemaGoalLine}s to {@link ReferenceLineProps} for the hog-charts
 *  primitive, preserving the `displayIfCrossed` filter. The filter drops a goal when
 *  `displayIfCrossed` is explicitly `false` *and* the line sits below the series peak —
 *  i.e. the data has already crossed it. */
export function goalLinesToReferenceLines(
    goalLines: SchemaGoalLine[] | null | undefined,
    series: Series[]
): ReferenceLineProps[] {
    if (!goalLines?.length) {
        return []
    }
    const seriesNonZeroMax = computeSeriesNonZeroMax(series)
    return goalLines
        .filter((goal) => goal.displayIfCrossed !== false || goal.value >= seriesNonZeroMax)
        .map(
            (goal): ReferenceLineProps => ({
                value: goal.value,
                orientation: 'horizontal',
                label: goal.displayLabel === false ? undefined : goal.label,
                labelPosition: goal.position ?? 'start',
                variant: 'goal',
                style: goal.borderColor ? { color: goal.borderColor } : undefined,
            })
        )
}
