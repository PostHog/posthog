import { max, mean, median, min } from 'd3'

import type { Series } from '@posthog/quill-charts'

import type { GoalLine } from '~/queries/schema/schema-general'

export function resolveSQLReferenceLines(
    lines: GoalLine[] | undefined,
    series: Series[],
    isPercentStack = false
): GoalLine[] {
    const primarySeries = series.filter((item) => item.yAxisId !== 'right' && !item.visibility?.excluded)
    return (lines ?? []).flatMap((line) => {
        if (!line.calculation || line.calculation === 'fixed') {
            return [line]
        }
        if (isPercentStack) {
            return []
        }
        const calculate: (values: number[]) => number | undefined = { mean, median, min, max }[line.calculation]
        const groups = line.scope === 'series' ? primarySeries.map((item) => [item]) : [primarySeries]
        return groups.flatMap((group) => {
            const values = group.flatMap((item) => item.data).filter(Number.isFinite)
            const value = calculate(values)
            return value === undefined || !Number.isFinite(value)
                ? []
                : [
                      {
                          ...line,
                          value,
                          label:
                              line.scope === 'series'
                                  ? [line.label, group[0].label].filter(Boolean).join(' · ')
                                  : line.label,
                      },
                  ]
        })
    })
}
