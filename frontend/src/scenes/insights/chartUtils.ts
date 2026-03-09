import type { GoalLine, LineProps, TooltipPoint } from 'lib/hog-charts'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import type { GoalLine as SchemaGoalLine } from '~/queries/schema/schema-general'
import type { CompareLabelType } from '~/types'

export function tooltipPointsToSeriesDatum(points: TooltipPoint[]): SeriesDatum[] {
    return points
        .filter((p) => !p.meta?.auxiliary)
        .map((point, idx) => ({
            id: idx,
            dataIndex: point.pointIndex,
            datasetIndex: point.seriesIndex,
            dotted: !!point.meta?.dotted,
            breakdown_value:
                (point.meta?.breakdown_value as string | number | string[] | undefined) ??
                (point.meta?.breakdownLabels as string[] | undefined)?.[point.pointIndex] ??
                (point.meta?.breakdownValues as string[] | undefined)?.[point.pointIndex],
            compare_label: point.meta?.compare_label as CompareLabelType | undefined,
            action: point.meta?.action as SeriesDatum['action'],
            label: point.seriesLabel,
            order: (point.meta?.order as number) ?? 0,
            color: point.color,
            count: point.value,
            filter: (point.meta?.filter ?? {}) as SeriesDatum['filter'],
        }))
        .sort((a, b) => b.count - a.count || (a.label ?? '').localeCompare(b.label ?? ''))
}

export function buildYAxis(
    isLog10: boolean,
    isPercentStackView: boolean,
    showMultipleYAxes: boolean | null,
    seriesCount: number
): LineProps['yAxis'] {
    const base = {
        startAtZero: !isLog10,
        scale: isLog10 ? ('logarithmic' as const) : ('linear' as const),
        gridLines: true,
        format: isPercentStackView ? ('percent' as const) : undefined,
    }

    if (showMultipleYAxes && seriesCount > 1) {
        return [base, { ...base, gridLines: false }]
    }

    return base
}

interface GoalLineInput {
    value: number
    label?: string | null
    borderColor?: string | null
}

export function buildGoalLines(
    alertThresholdLines: GoalLineInput[],
    schemaGoalLines: SchemaGoalLine[] | undefined
): GoalLine[] {
    const all = [...alertThresholdLines, ...(schemaGoalLines || [])]
    return all.map((gl) => ({
        value: gl.value,
        label: gl.label ?? undefined,
        color: gl.borderColor ?? undefined,
        style: 'dashed' as const,
    }))
}

export function resolveGroupTypeLabel(
    contextLabel: string | undefined,
    labelGroupType: string | number | null | undefined,
    aggregationLabel: (groupTypeIndex: number) => { singular: string; plural: string }
): string | undefined {
    if (contextLabel) {
        return contextLabel
    }
    if (labelGroupType === 'people') {
        return 'people'
    }
    if (labelGroupType === 'none') {
        return ''
    }
    if (typeof labelGroupType === 'number') {
        return aggregationLabel(labelGroupType).plural
    }
    return undefined
}
