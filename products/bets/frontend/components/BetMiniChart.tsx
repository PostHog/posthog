import { useMemo } from 'react'

import {
    AnomalyPointsLayer,
    DEFAULT_Y_AXIS_ID,
    DefaultTooltip,
    LineChart,
    ReferenceLine,
    type LineChartProps,
    type TooltipContext,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

const MARGINS = { top: 10, bottom: 4, left: 6, right: 6 }

export function BetMiniChart({
    label,
    labels,
    values,
    limit,
    limitLabel,
    formatValue,
    formatLabel,
    floor,
    empty,
    ticks,
}: {
    label: string
    labels: string[]
    values: number[]
    limit: number | null
    limitLabel: string
    formatValue: (value: number) => string
    formatLabel: (label: string) => string
    floor?: number
    empty?: string
    ticks: string[]
}): JSX.Element {
    const theme = useChartTheme()
    const padded = values.length < 2
    const chartLabels = useMemo(
        () => (padded ? ['', ...labels, ...(labels.length ? [] : [' '])] : labels),
        [padded, labels]
    )
    const series = useMemo(
        () => [
            {
                key: 'value',
                label,
                data: padded ? [NaN, ...values, ...(values.length ? [] : [NaN])] : values,
                color: theme.axisColor,
                points: { radius: 0 },
            },
        ],
        [label, padded, values, theme.axisColor]
    )
    const markers = useMemo(
        () =>
            values.length && theme.axisColor
                ? [
                      {
                          dataIndex: (padded ? 1 : 0) + values.length - 1,
                          value: values[values.length - 1],
                          color: theme.axisColor,
                          yAxisId: DEFAULT_Y_AXIS_ID,
                      },
                  ]
                : [],
        [values, padded, theme.axisColor]
    )
    const known = [...values, ...(limit === null ? [] : [limit]), ...(floor === undefined ? [] : [floor])]
    const minimum = known.length ? Math.min(...known) : 0
    const maximum = known.length ? Math.max(...known) : 1
    const padding = Math.max((maximum - minimum) * 0.15, Math.abs(maximum) * 0.05, 0.01)
    const config: LineChartProps['config'] = useMemo(
        () => ({
            margins: MARGINS,
            showGrid: false,
            showAxisLines: { x: true, y: false },
            hideYAxis: true,
            hideXAxis: true,
            valueDomain: {
                min: floor === undefined ? minimum - padding : floor,
                max: maximum + padding,
            },
            tooltip: { enabled: values.length > 0, placement: 'top' },
        }),
        [floor, minimum, maximum, padding, values.length]
    )
    const tooltip = useMemo(
        () =>
            (context: TooltipContext): JSX.Element | null =>
                context.seriesData.every((entry) => Number.isNaN(entry.value)) ? null : (
                    <DefaultTooltip {...context} valueFormatter={formatValue} labelFormatter={formatLabel} />
                ),
        [formatValue, formatLabel]
    )
    return (
        <div className="relative flex h-28 min-w-0 flex-col" role="img" aria-label={label}>
            <LineChart series={series} labels={chartLabels} theme={theme} config={config} tooltip={tooltip}>
                <AnomalyPointsLayer markers={markers} radius={3} />
                {limit !== null && (
                    <ReferenceLine
                        value={limit}
                        orientation="horizontal"
                        variant="goal"
                        style={{ color: 'var(--color-graph-axis-label)' }}
                        label={limitLabel}
                        labelPosition="start"
                        showValueOnHover={false}
                    />
                )}
            </LineChart>
            {empty && <span className="Bets__miniChartEmpty pointer-events-none absolute text-center">{empty}</span>}
            <div className="Bets__miniChartAxis mt-1 flex min-h-4 justify-between tabular-nums" aria-hidden>
                {ticks.map((tick, index) => (
                    <span key={index}>{tick}</span>
                ))}
            </div>
        </div>
    )
}
