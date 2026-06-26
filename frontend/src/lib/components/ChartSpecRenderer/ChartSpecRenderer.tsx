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
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type TooltipConfig,
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

function toTooltipConfig(config: ChartSpec['config']): TooltipConfig | undefined {
    if (!config?.tooltipShowTotal && !config?.tooltipPlacement) {
        return undefined
    }
    return { showTotal: config.tooltipShowTotal, placement: config.tooltipPlacement }
}

// Detects when bar chart labels are ISO date strings so we can swap to TimeSeriesBarChart.
function looksLikeISODate(label: string): boolean {
    return /^\d{4}-\d{2}-\d{2}T/.test(label)
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
                    showAxisLines: spec.config?.showAxisLines,
                    showCrosshair: spec.config?.showCrosshair,
                    hideXAxis: spec.config?.hideXAxis,
                    hideYAxis: spec.config?.hideYAxis,
                    tooltip: toTooltipConfig(spec.config),
                    yAxes: toQuillYAxes(spec.axes),
                    yTickFormatter: primaryAxis ? formatterFor(primaryAxis.format, primaryAxis.currency) : undefined,
                    floatBaseline: primaryAxis?.startAtZero === false,
                    legend: {
                        show: spec.config?.showLegend ?? spec.config?.legendPosition != null,
                        position: spec.config?.legendPosition,
                        align: spec.config?.legendAlign,
                    },
                }
                return (
                    <LineChart series={series} labels={spec.labels} config={config} theme={theme}>
                        {spec.config?.showValueLabels && <ValueLabels />}
                        {refLines}
                    </LineChart>
                )
            }
            case 'timeSeriesBar':
            // eslint-disable-next-line no-fallthrough
            case 'bar': {
                const isTimeSeries =
                    spec.chartType === 'timeSeriesBar' || (spec.labels.length > 0 && looksLikeISODate(spec.labels[0]))

                if (isTimeSeries) {
                    const yAxisConfig: YAxisConfig | undefined = primaryAxis
                        ? {
                              id: primaryAxis.id,
                              position: primaryAxis.id,
                              format: primaryAxis.format,
                              currency: primaryAxis.currency,
                              scale: primaryAxis.scale,
                              label: primaryAxis.label,
                              startAtZero: primaryAxis.startAtZero,
                          }
                        : undefined
                    const tsBarConfig: TimeSeriesBarChartConfig = {
                        xAxis: { timezone: 'UTC', interval: 'day' },
                        yAxis: yAxisConfig,
                        barLayout: barLayout(spec.config),
                        barCornerRadius: 4,
                        divergingStack: spec.config?.divergingStack,
                        fillStyle: spec.config?.barFillStyle,
                        showCrosshair: spec.config?.showCrosshair,
                        showAxisLines: spec.config?.showAxisLines,
                        tooltip: toTooltipConfig(spec.config),
                        legend: {
                            show: spec.config?.showLegend ?? spec.config?.legendPosition != null,
                            position: spec.config?.legendPosition,
                            align: spec.config?.legendAlign,
                        },
                    }
                    return (
                        <TimeSeriesBarChart series={series} labels={spec.labels} config={tsBarConfig} theme={theme}>
                            {spec.config?.showValueLabels && <ValueLabels />}
                            {refLines}
                        </TimeSeriesBarChart>
                    )
                }

                const barConfig: BarChartConfig = {
                    barLayout: barLayout(spec.config),
                    axisOrientation: spec.config?.horizontal ? 'horizontal' : 'vertical',
                    showGrid: spec.config?.showGrid,
                    showAxisLines: spec.config?.showAxisLines,
                    showCrosshair: spec.config?.showCrosshair,
                    hideXAxis: spec.config?.hideXAxis,
                    hideYAxis: spec.config?.hideYAxis,
                    tooltip: toTooltipConfig(spec.config),
                    yAxes: toQuillYAxes(spec.axes),
                    yTickFormatter: primaryAxis ? formatterFor(primaryAxis.format, primaryAxis.currency) : undefined,
                    bars: {
                        cornerRadius: 4,
                        fillStyle: spec.config?.barFillStyle,
                        divergingStack: spec.config?.divergingStack,
                        roundStackEnds: spec.config?.roundStackEnds,
                    },
                    legend: {
                        show: spec.config?.showLegend ?? spec.config?.legendPosition != null,
                        position: spec.config?.legendPosition,
                        align: spec.config?.legendAlign,
                    },
                }
                return (
                    <BarChart series={series} labels={spec.labels} config={barConfig} theme={theme}>
                        {spec.config?.showValueLabels && <ValueLabels />}
                        {refLines}
                    </BarChart>
                )
            }
            case 'combo': {
                const config: ComboChartConfig = {
                    barLayout: spec.config?.grouped ? 'grouped' : 'stacked',
                    showGrid: spec.config?.showGrid,
                    showAxisLines: spec.config?.showAxisLines,
                    showCrosshair: spec.config?.showCrosshair,
                    hideXAxis: spec.config?.hideXAxis,
                    hideYAxis: spec.config?.hideYAxis,
                    tooltip: toTooltipConfig(spec.config),
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
                    showCrosshair: spec.config?.showCrosshair,
                    showAxisLines: spec.config?.showAxisLines,
                    tooltip: toTooltipConfig(spec.config),
                    legend: {
                        show: spec.config?.showLegend ?? spec.config?.legendPosition != null,
                        position: spec.config?.legendPosition,
                        align: spec.config?.legendAlign,
                    },
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
                const innerRadiusRatio = spec.config?.innerRadiusRatio ?? (spec.config?.donut ? 0.6 : 0)
                return (
                    <PieChart
                        series={sliceSeries}
                        config={{ innerRadiusRatio, showLabelOnSlice: true }}
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
                        showChange={spec.config?.showChange ?? true}
                        goodDirection={spec.config?.goodDirection}
                        changeInline={spec.config?.changeInline}
                        sparklineFill={spec.config?.sparklineFill}
                        subtitle={spec.config?.subtitle}
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
            <div style={isCard ? undefined : { height }} className={isCard ? undefined : 'flex flex-col'}>
                {body}
            </div>
            {spec.narrative && <div className="text-xs text-secondary mt-2">{spec.narrative}</div>}
        </div>
    )
}
