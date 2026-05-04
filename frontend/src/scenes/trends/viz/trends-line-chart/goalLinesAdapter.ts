import { buildGoalLineReferenceLines, computeSeriesNonZeroMax } from 'lib/hog-charts'
import type { GoalLineConfig, ReferenceLineProps, Series } from 'lib/hog-charts'

import type { GoalLine as SchemaGoalLine } from '~/queries/schema/schema-general'

// Re-exported so existing call sites importing from this adapter keep working.
export { computeSeriesNonZeroMax }

function schemaToGoalLineConfig(line: SchemaGoalLine): GoalLineConfig {
    return {
        value: line.value,
        label: line.label,
        displayLabel: line.displayLabel,
        color: line.borderColor,
        labelPosition: line.position,
        displayIfCrossed: line.displayIfCrossed,
    }
}

function schemaToReferenceLine(line: SchemaGoalLine, variant: 'goal' | 'alert'): ReferenceLineProps {
    return {
        value: line.value,
        orientation: 'horizontal',
        label: line.displayLabel === false ? undefined : line.label,
        labelPosition: line.position ?? 'start',
        variant,
        style: line.borderColor ? { color: line.borderColor } : undefined,
    }
}

function withAxisOrientation(
    refs: ReferenceLineProps[],
    axisOrientation: 'vertical' | 'horizontal' | undefined
): ReferenceLineProps[] {
    return axisOrientation === 'horizontal' ? refs.map((r) => ({ ...r, axisOrientation })) : refs
}

/** Map persisted {@link SchemaGoalLine}s to {@link ReferenceLineProps} for the hog-charts
 *  primitive, preserving the `displayIfCrossed` filter. The filter drops a goal when
 *  `displayIfCrossed` is explicitly `false` *and* the line sits below the series peak —
 *  i.e. the data has already crossed it. Pass `axisOrientation: 'horizontal'` when the
 *  chart's value axis is horizontal (e.g. horizontal bar charts) to flip rendering. */
export function goalLinesToReferenceLines(
    goalLines: SchemaGoalLine[] | null | undefined,
    series: Series[],
    axisOrientation?: 'vertical' | 'horizontal'
): ReferenceLineProps[] {
    if (!goalLines?.length) {
        return []
    }
    const refs = buildGoalLineReferenceLines(goalLines.map(schemaToGoalLineConfig), series)
    return withAxisOrientation(refs, axisOrientation)
}

/** Map alert threshold lines (sourced from `insightAlertsLogic.alertThresholdLines`) to
 *  {@link ReferenceLineProps}. Same shape as goal lines, but rendered with the `alert`
 *  variant (dashed red) so they read as bounds, not targets. */
export function alertThresholdsToReferenceLines(
    alertThresholdLines: SchemaGoalLine[] | null | undefined,
    axisOrientation?: 'vertical' | 'horizontal'
): ReferenceLineProps[] {
    if (!alertThresholdLines?.length) {
        return []
    }
    const refs = alertThresholdLines.map((line) => schemaToReferenceLine(line, 'alert'))
    return withAxisOrientation(refs, axisOrientation)
}
