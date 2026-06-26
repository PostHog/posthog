import {
    BarChart,
    type BarChartConfig,
    buildYTickFormatter,
    ComboChart,
    type ComboChartConfig,
    LineChart,
    type LineChartConfig,
    MetricCard,
    PieChart,
    ReferenceLine,
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    useChartTheme,
    ValueLabels,
    type YAxis,
    type YAxisConfig,
} from '@posthog/quill-charts'

import type { ChartSpec, ChartSpecAxis, ChartSpecReferenceLine, ChartSpecValueFormat } from './chartSpec'

function formatterFor(format?: ChartSpecValueFormat, currency?: string): ((value: number) => string) | undefined {
    if (!format) {
        return undefined
    }
    return buildYTickFormatter({ format, currency })
}

// Spec series → quill series. `fill`/`dashed` are translated to the structured stroke/fill props.
function toQuillSeries(spec: ChartSpec): Series[] {
    return spec.series.map((s) => ({
        key: s.key,
        label: s.label,
        data: s.data,
        color: s.color,
        type: s.type,
        yAxisId: s.axis,
        fill: s.fill ? { opacity: 0.25, gradient: true } : undefined,
        stroke: s.dashed ? { pattern: [6, 6] } : undefined,
    }))
}

// Spec axes → quill `YAxis[]` (used by the band/line/combo charts via `config.yAxes`).
function toQuillYAxes(axes?: ChartSpecAxis[]): YAxis[] | undefined {
    if (!axes?.length) {
        return undefined
    }
    return axes.map((a) => ({
        id: a.id,
        position: a.id,
        scaleType: a.scale,
        tickFormatter: formatterFor(a.format, a.currency),
        label: a.label,
    }))
}

function referenceLineChildren(lines?: ChartSpecReferenceLine[]): JSX.Element[] | null {
    if (!lines?.length) {
        return null
    }
    return lines.map((line, i) => (
        <ReferenceLine
            key={i}
            value={line.value}
            orientation={line.orientation ?? 'horizontal'}
            label={line.label}
            variant={line.variant ?? 'goal'}
            yAxisId={line.axis}
        />
    ))
}

function barLayout(config: ChartSpec['config']): 'stacked' | 'grouped' | 'percent' {
    if (config?.percent) {
        return 'percent'
    }
    if (config?.grouped) {
        return 'grouped'
    }
    return 'stacked'
}

export interface ChartSpecRendererProps {
    spec: ChartSpec
    /** Height in px for the chart body. Pie/line/bar/combo fill this; MetricCard ignores it. */
    height?: number
    className?: string
}

/** Renders a declarative {@link ChartSpec} into the matching `@posthog/quill-charts` component.
 *  This is the "render half" of the gen-UI charts idea — an LLM emits the spec, this draws it. */
export function ChartSpecRenderer({ spec, height = 320, className }: ChartSpecRendererProps): JSX.Element {
    const theme = useChartTheme()
    const series = toQuillSeries(spec)
    const refLines = referenceLineChildren(spec.referenceLines)
    const primaryAxis = spec.axes?.[0]

    const body = ((): JSX.Element => {
        switch (spec.chartType) {
            case 'line': {
                const config: LineChartConfig = {
                    showGrid: spec.config?.showGrid,
                    yAxes: toQuillYAxes(spec.axes),
                    yTickFormatter: primaryAxis ? formatterFor(primaryAxis.format, primaryAxis.currency) : undefined,
                    floatBaseline: primaryAxis?.startAtZero === false,
                    legend: { show: spec.config?.showLegend },
                }
                return (
                    <LineChart series={series} labels={spec.labels} config={config} theme={theme}>
                        {spec.config?.showValueLabels && <ValueLabels />}
                        {refLines}
                    </LineChart>
                )
            }
            case 'bar': {
                const config: BarChartConfig = {
                    barLayout: barLayout(spec.config),
                    axisOrientation: spec.config?.horizontal ? 'horizontal' : 'vertical',
                    showGrid: spec.config?.showGrid,
                    yAxes: toQuillYAxes(spec.axes),
                    yTickFormatter: primaryAxis ? formatterFor(primaryAxis.format, primaryAxis.currency) : undefined,
                    bars: { cornerRadius: 4 },
                    legend: { show: spec.config?.showLegend },
                }
                return (
                    <BarChart series={series} labels={spec.labels} config={config} theme={theme}>
                        {spec.config?.showValueLabels && <ValueLabels />}
                        {refLines}
                    </BarChart>
                )
            }
            case 'combo': {
                const config: ComboChartConfig = {
                    barLayout: spec.config?.grouped ? 'grouped' : 'stacked',
                    showGrid: spec.config?.showGrid,
                    yAxes: toQuillYAxes(spec.axes),
                    yTickFormatter: primaryAxis ? formatterFor(primaryAxis.format, primaryAxis.currency) : undefined,
                    barCornerRadius: 4,
                }
                return (
                    <ComboChart series={series} labels={spec.labels} config={config} theme={theme}>
                        {refLines}
                    </ComboChart>
                )
            }
            case 'timeSeriesLine': {
                const yAxis: YAxisConfig[] | undefined = spec.axes?.map((a) => ({
                    id: a.id,
                    position: a.id,
                    format: a.format,
                    currency: a.currency,
                    scale: a.scale,
                    label: a.label,
                    startAtZero: a.startAtZero,
                }))
                const config: TimeSeriesLineChartConfig = {
                    xAxis: { timezone: 'UTC', interval: 'day' },
                    yAxis,
                    valueLabels: spec.config?.showValueLabels,
                    legend: { show: spec.config?.showLegend },
                }
                return (
                    <TimeSeriesLineChart series={series} labels={spec.labels} config={config} theme={theme}>
                        {refLines}
                    </TimeSeriesLineChart>
                )
            }
            case 'pie': {
                // One slice per label, taken from the first series.
                const first = spec.series[0]
                const sliceSeries: Series[] = spec.labels.map((label, i) => ({
                    key: `${first.key}-${i}`,
                    label,
                    data: [first.data[i] ?? 0],
                }))
                return (
                    <PieChart
                        series={sliceSeries}
                        config={{ innerRadiusRatio: spec.config?.donut ? 0.6 : 0, showLabelOnSlice: true }}
                        valueFormatter={formatterFor(primaryAxis?.format, primaryAxis?.currency)}
                        theme={theme}
                    />
                )
            }
            case 'metricCard': {
                const first = spec.series[0]
                return (
                    <MetricCard
                        title={spec.title ?? first.label}
                        data={first.data}
                        labels={spec.labels}
                        theme={theme}
                        color={first.color}
                        formatValue={formatterFor(primaryAxis?.format, primaryAxis?.currency)}
                        showChange
                    />
                )
            }
        }
    })()

    const isCard = spec.chartType === 'metricCard'

    return (
        <div className={className}>
            {spec.title && !isCard && <div className="text-sm font-semibold mb-1">{spec.title}</div>}
            {/* eslint-disable-next-line react/forbid-dom-props -- chart body needs an explicit pixel height */}
            <div style={isCard ? undefined : { height }}>{body}</div>
            {spec.narrative && <div className="text-xs text-secondary mt-2">{spec.narrative}</div>}
        </div>
    )
}
