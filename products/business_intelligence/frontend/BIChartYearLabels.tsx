import { useChartLayout } from '@posthog/quill-charts'

import { getBIChartYearGroups } from './biChartDateAxis'

export function BIChartYearLabels({ timezone }: { timezone: string }): JSX.Element {
    const { labels, scales, dimensions, theme } = useChartLayout()
    const groups = getBIChartYearGroups(labels, timezone)
    return (
        <div className="pointer-events-none" aria-label="Years">
            {groups.map(({ year, first, last }, index) => {
                const start = scales.x(first)
                const end = scales.x(last)
                if (start === undefined || end === undefined) {
                    return null
                }
                return (
                    <span
                        key={`${year}-${index}`}
                        data-attr="bi-chart-year"
                        className="absolute -translate-x-1/2 text-xs whitespace-nowrap"
                        // The year spans chart coordinates, which change with the plot's measured size.
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: (start + end) / 2,
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
