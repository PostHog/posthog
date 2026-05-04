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
    return buildGoalLineReferenceLines(goalLines.map(schemaToGoalLineConfig), series)
}

/** Map alert threshold lines (sourced from `insightAlertsLogic.alertThresholdLines`) to
 *  {@link ReferenceLineProps}. Same shape as goal lines, but rendered with the `alert`
 *  variant (dashed red) so they read as bounds, not targets. */
export function alertThresholdsToReferenceLines(
    alertThresholdLines: SchemaGoalLine[] | null | undefined
): ReferenceLineProps[] {
    if (!alertThresholdLines?.length) {
        return []
    }
    return alertThresholdLines.map((line) => schemaToReferenceLine(line, 'alert'))
}
