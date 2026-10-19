import { useChartLayout } from '@posthog/quill-charts'

import { getBIChartYearGroups } from './biChartDateAxis'

export function BIChartYearLabels({ timezone }: { timezone: string }): JSX.Element {
    const { labels, scales, dimensions, theme } = useChartLayout()
    const groups = getBIChartYearGroups(labels, timezone)
    let nextLabelStart = dimensions.plotLeft
    return (
        <div className="pointer-events-none" aria-label="Years">
            {groups.map(({ year, first, last }, index) => {
                const start = scales.x(first)
                const end = scales.x(last)
                if (start === undefined || end === undefined) {
                    return null
                }
                const left = Math.max(dimensions.plotLeft, start - (scales.extent?.(first) ?? 0) / 2)
                if (left < nextLabelStart || left + 36 > dimensions.plotLeft + dimensions.plotWidth) {
                    return null
                }
                nextLabelStart = left + 48
                return (
                    <span
                        key={`${year}-${index}`}
                        data-attr="bi-chart-year"
                        className="absolute text-xs whitespace-nowrap"
                        // The year spans chart coordinates, which change with the plot's measured size.
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left,
                            top: dimensions.plotTop + dimensions.plotHeight + 28,
                            color: theme.axisColor,
                        }}
                    >
                        {year}
                    </span>
                )
            })}
        </div>
    )
}
