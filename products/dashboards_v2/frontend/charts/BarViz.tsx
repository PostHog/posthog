import { BarChart, MAX_CATEGORY_LABEL_WIDTH, TimeSeriesBarChart, ValueLabels } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { colorToken, fieldOverride, thresholdColor, tooltipFor, withOverrides, xAxisFor, yAxisFor } from './chartCommon'
import { colorize } from './colors'
import { bucketOf, seriesOrigin } from './drilldown'
import { EmptyData } from './EmptyData'
import { drawnIncomplete, hasTime, toCategories, toTimeSeries } from './frames'
import { FunnelBars } from './FunnelBars'
import type { BarOptions as O } from './options'
import type { VizProps } from './registry'

export function BarViz({ frames, panel, options, timezone, onDrill }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const yAxis = (
        unit?: string
    ): {
        label?: string | undefined
        tickFormatter: (v: number) => string
        min: number | undefined
        max: number | undefined
        startAtZero: boolean
    } => ({
        ...yAxisFor(panel, unit),
        ...(options.axisLabel ? { label: options.axisLabel } : {}),
    })
    const valueLabels = (unit?: string): { formatter: (v: number) => string } | undefined =>
        options.showValues ? { formatter: tooltipFor(panel, unit).valueFormatter } : undefined
    if (hasTime(frames)) {
        const { labels } = toTimeSeries(frames)
        const series = colorize(panel, withOverrides(panel, toTimeSeries(frames).series), theme.colors)
        if (!series.length) {
            return <EmptyData />
        }
        const partial = drawnIncomplete(panel, frames, labels.map(Date.parse))
        return (
            <TimeSeriesBarChart
                onPointClick={
                    onDrill
                        ? (((d: any) => {
                              const s = series[d.seriesIndex]
                              const o = s ? seriesOrigin(frames, s.key) : {}
                              onDrill({
                                  refId: o.refId,
                                  series: s && { name: s.label, labels: o.labels },
                                  value: d.value,
                                  time: bucketOf(labels, d.dataIndex),
                              })
                          }) as never)
                        : undefined
                }
                className="min-h-0 flex-1"
                theme={theme}
                labels={labels}
                series={series.map((s) => ({
                    key: s.key,
                    label: s.label,
                    data: s.data,
                    color: s.color,
                    ...(partial >= 0 ? { bars: s.data.map((_, j) => ({ hatch: j >= partial })) } : {}),
                }))}
                config={{
                    barLayout: options.stack ? 'stacked' : 'grouped',
                    fillStyle: options.barStyle,
                    showGrid: true,
                    xAxis: {
                        interval: xAxisFor(labels, timezone).interval,
                        tickFormatter: xAxisFor(labels, timezone).tickFormatter,
                    },
                    yAxis: yAxis(series[0]?.unit),
                    valueLabels: valueLabels(series[0]?.unit),
                    tooltip: {
                        ...tooltipFor(panel, series[0]?.unit),
                        labelFormatter: xAxisFor(labels, timezone).labelFormatter,
                    },
                    legend: {
                        show: options.legend !== 'none' && series.length > 1,
                        position: options.legend === 'none' ? 'bottom' : options.legend,
                    },
                }}
            />
        )
    }
    const cats = sortCategories(toCategories(frames), options.sort)
    const { unit } = cats
    const series = colorize(panel, withOverrides(panel, cats.series), theme.colors)
    if (!cats.labels.length) {
        return <EmptyData />
    }
    const labels = cats.labels.map((l) => fieldOverride(panel, l)?.displayName ?? l)
    const catCol =
        frames.find((f) => f.fields.some((x) => x.type === 'string'))?.fields.find((x) => x.type === 'string')?.name ??
        'category'
    const drillAt = (si: number, i: number, value: number, step?: { dropoff?: boolean }): void => {
        const s = series[si],
            o = s ? seriesOrigin(frames, s.key) : {}
        onDrill?.({
            refId: o.refId,
            series: s && { name: s.label, labels: o.labels },
            value,
            category: cats.labels[i],
            row: { [catCol]: cats.labels[i], ...(s ? { [s.label]: s.data[i] } : {}) },
            ...(step ? { step: { index: i, name: cats.labels[i]!, dropoff: step.dropoff } } : {}),
        })
    }
    if (options.funnel && !options.stack) {
        return (
            <FunnelBars
                labels={labels}
                series={series}
                theme={theme}
                stepReference={options.stepReference}
                horizontal={options.horizontal}
                format={(v) =>
                    (panel.fieldConfig?.unit ?? unit) ? tooltipFor(panel, unit).valueFormatter(v) : v.toLocaleString()
                }
                onStep={onDrill ? (si, i, dropoff) => drillAt(si, i, series[si]?.data[i] ?? 0, { dropoff }) : undefined}
            />
        )
    }
    const thresholds = panel.fieldConfig?.color?.mode === 'thresholds'
    const named = cats.labels.map((l) => {
        const c = fieldOverride(panel, l)?.color
        return c ? colorToken(c) : undefined
    })
    const perBar = series.length === 1 && (!!options.colorBars || thresholds || named.some(Boolean))
    const barColor = (i: number): string =>
        named[i] ??
        (thresholds ? thresholdColor(series[0]!.data[i] ?? null, panel) : undefined) ??
        (options.colorBars ? theme.colors[i % theme.colors.length]! : series[0]!.color)
    return (
        <BarChart
            onPointClick={onDrill ? (((d: any) => drillAt(d.seriesIndex, d.dataIndex, d.value)) as never) : undefined}
            className="min-h-0 flex-1"
            theme={theme}
            labels={labels}
            series={series.map((s) => ({
                key: s.key,
                label: s.label,
                data: s.data,
                color: s.color,
                ...(perBar ? { bars: labels.map((_, i) => ({ color: barColor(i) })) } : {}),
            }))}
            config={{
                barLayout: options.stack ? 'stacked' : 'grouped',
                bars: {
                    fillStyle: options.barStyle,
                    fitToHeight: true,
                    ...(options.showValues ? { valuePadding: 48 } : {}),
                },
                axisOrientation: options.horizontal ? 'horizontal' : 'vertical',
                maxCategoryLabelWidth: MAX_CATEGORY_LABEL_WIDTH,
                showGrid: true,
                yTickFormatter: yAxisFor(panel, unit).tickFormatter,
                ...(options.axisLabel ? { [options.horizontal ? 'xAxisLabel' : 'yAxisLabel']: options.axisLabel } : {}),
                tooltip: { ...tooltipFor(panel, unit), labelFormatter: xAxisFor(labels, timezone).labelFormatter },
                legend: {
                    show: options.legend !== 'none' && series.length > 1,
                    position: options.legend === 'none' ? 'bottom' : options.legend,
                },
            }}
        >
            {options.showValues && (
                <ValueLabels valueFormatter={tooltipFor(panel, unit).valueFormatter} background={false} />
            )}
        </BarChart>
    )
}

export function sortCategories<C extends { labels: string[]; series: { data: number[] }[] }>(c: C, sort: O['sort']): C {
    if (!sort || sort === 'query') {
        return c
    }
    const first = c.series[0]?.data ?? []
    const order = c.labels
        .map((_, i) => i)
        .sort(
            sort === 'label'
                ? (a, b) => c.labels[a]!.localeCompare(c.labels[b]!, undefined, { numeric: true })
                : (a, b) => (first[b] ?? 0) - (first[a] ?? 0)
        )
    return {
        ...c,
        labels: order.map((i) => c.labels[i]!),
        series: c.series.map((s) => ({ ...s, data: order.map((i) => s.data[i]!) })),
    }
}
