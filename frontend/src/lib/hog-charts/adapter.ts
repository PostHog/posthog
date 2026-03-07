/**
 * Chart.js adapter — translates HogCharts props into Chart.js configs.
 *
 * This is the only file that knows about Chart.js. If we ever swap rendering
 * engines, only this file needs to change.
 */

import type { ChartConfiguration, ChartDataset } from 'chart.js'

import { formatValue } from './format'
import { mergeTheme, seriesColor } from './theme'
import type {
    AreaProps,
    AxisConfig,
    BarProps,
    BaseChartProps,
    BoxPlotProps,
    GoalLine,
    HogChartTheme,
    LifecycleProps,
    LineProps,
    PieProps,
    Series,
    TimeSeriesProps,
    TooltipContext,
    TooltipPoint,
} from './types'

// ---------------------------------------------------------------------------
// Tooltip callback type — used by hooks to bridge Chart.js → HogCharts
// ---------------------------------------------------------------------------

export interface TooltipCallbacks {
    onShow: (context: TooltipContext) => void
    onHide: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveColor(series: Series, index: number, theme: HogChartTheme): string {
    return series.color ?? seriesColor(theme, index)
}

function buildScaleConfig(
    axis: AxisConfig | undefined,
    theme: HogChartTheme,
    defaults?: Partial<AxisConfig>
): Record<string, unknown> {
    const merged = { ...defaults, ...axis }
    return {
        display: true,
        title: merged.label ? { display: true, text: merged.label, color: theme.axisColor } : undefined,
        grid: {
            display: merged.gridLines ?? defaults?.gridLines ?? false,
            color: theme.gridColor,
        },
        ticks: {
            color: theme.axisColor,
            callback: merged.format
                ? function (this: unknown, tickValue: string | number): string {
                      return formatValue(Number(tickValue), merged.format, {
                          prefix: merged.prefix,
                          suffix: merged.suffix,
                          decimalPlaces: merged.decimalPlaces,
                      })
                  }
                : undefined,
        },
        min: merged.min,
        max: merged.max,
        beginAtZero: merged.startAtZero,
        type: merged.scale === 'logarithmic' ? 'logarithmic' : 'linear',
    }
}

function buildGoalLineAnnotations(
    goalLines: GoalLine[] | undefined,
    theme: HogChartTheme
): Record<string, unknown>[] {
    if (!goalLines?.length) {
        return []
    }
    return goalLines.map((gl, i) => ({
        type: 'line',
        id: `goal-${i}`,
        scaleID: 'y',
        value: gl.value,
        borderColor: gl.color ?? theme.goalLineColor,
        borderWidth: 2,
        borderDash: gl.style === 'dotted' ? [2, 4] : gl.style === 'solid' ? [] : [6, 4],
        label: gl.label
            ? {
                  display: true,
                  content: gl.label,
                  position: 'start',
                  backgroundColor: gl.color ?? theme.goalLineColor,
                  color: '#fff',
                  font: { size: 11 },
                  padding: { x: 6, y: 3 },
              }
            : undefined,
    }))
}

function baseOptions(
    props: BaseChartProps,
    theme: HogChartTheme,
    seriesData?: Series[]
): Record<string, unknown> {
    const hasCustomTooltip = !!props.tooltip?.render
    const shared = props.tooltip?.shared ?? true

    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: props.animate ? undefined : false,
        plugins: {
            legend: {
                display: (props.legend?.position ?? 'bottom') !== 'none',
                position: props.legend?.position ?? 'bottom',
                labels: {
                    color: theme.axisColor,
                    font: { family: theme.fontFamily, size: theme.fontSize },
                    usePointStyle: true,
                    pointStyle: 'circle',
                    boxWidth: 8,
                },
            },
            tooltip: hasCustomTooltip
                ? {
                      // Disable Chart.js native tooltip — we use our own portal
                      enabled: false,
                      mode: shared ? 'index' : 'nearest',
                      intersect: !shared,
                      // External handler is injected by useHogChart via _hogTooltipMeta
                  }
                : {
                      enabled: true,
                      mode: shared ? 'index' : 'nearest',
                      intersect: !shared,
                      backgroundColor: theme.tooltipBackground,
                      titleColor: theme.tooltipColor,
                      bodyColor: theme.tooltipColor,
                      cornerRadius: theme.tooltipBorderRadius,
                      padding: 10,
                      titleFont: { family: theme.fontFamily },
                      bodyFont: { family: theme.fontFamily },
                  },
        },
        layout: {
            padding: { top: 4, right: 8, bottom: 4, left: 8 },
        },
        // Stash metadata so the hook can build TooltipContext from Chart.js callbacks
        _hogTooltipMeta: {
            seriesData: seriesData ?? [],
            theme,
        },
    }
}

// ---------------------------------------------------------------------------
// Line chart
// ---------------------------------------------------------------------------

export function buildLineConfig(props: LineProps): ChartConfiguration<'line'> {
    const theme = mergeTheme(props.theme)
    const datasets: ChartDataset<'line'>[] = props.data.map((s, i) => {
        let data = s.data
        if (props.cumulative) {
            let sum = 0
            data = data.map((v) => (sum += v))
        }
        return {
            label: s.label,
            data,
            borderColor: resolveColor(s, i, theme),
            backgroundColor: `${resolveColor(s, i, theme)}18`,
            borderWidth: props.lineWidth ?? 2,
            pointRadius: resolvePointRadius(props.showDots, props.data[0]?.data.length ?? 0),
            pointHoverRadius: 5,
            tension: props.interpolation === 'smooth' ? 0.35 : 0,
            stepped: props.interpolation === 'step' ? 'before' : false,
            hidden: s.hidden,
            fill: false,
            _hogMeta: s.meta,
        } as ChartDataset<'line'>
    })

    if (props.compare) {
        for (const cs of props.compare) {
            datasets.push({
                label: `${cs.label} (${cs.compareLabel})`,
                data: cs.data,
                borderColor: `${resolveColor(cs, datasets.length, theme)}60`,
                backgroundColor: 'transparent',
                borderWidth: (props.lineWidth ?? 2) - 0.5,
                borderDash: [6, 4],
                pointRadius: 0,
                hidden: cs.hidden,
                fill: false,
            })
        }
    }

    const yAxes = buildYAxes(props, theme)

    const opts = baseOptions(props, theme, props.data)
    return {
        type: 'line',
        data: { labels: props.labels, datasets },
        options: {
            ...opts,
            scales: {
                x: buildScaleConfig(props.xAxis, theme) as never,
                ...yAxes,
            },
            plugins: {
                ...(opts.plugins as Record<string, unknown>),
                annotation: {
                    annotations: buildGoalLineAnnotations(props.goalLines, theme),
                },
                datalabels: props.showValues ? { display: true, color: theme.axisColor } : { display: false },
            },
        } as never,
    }
}

function resolvePointRadius(showDots: boolean | 'auto' | undefined, pointCount: number): number {
    if (showDots === true) {
        return 3
    }
    if (showDots === false) {
        return 0
    }
    // 'auto' or undefined
    return pointCount <= 30 ? 3 : 0
}

// ---------------------------------------------------------------------------
// Area chart
// ---------------------------------------------------------------------------

export function buildAreaConfig(props: AreaProps): ChartConfiguration<'line'> {
    const config = buildLineConfig(props)
    const opacity = Math.round((props.fillOpacity ?? 0.1) * 255)
        .toString(16)
        .padStart(2, '0')
    const theme = mergeTheme(props.theme)

    for (const [i, ds] of config.data.datasets.entries()) {
        ;(ds as ChartDataset<'line'>).fill = props.stacked || props.stacked100 ? 'origin' : true
        ;(ds as ChartDataset<'line'>).backgroundColor = `${resolveColor(props.data[i] ?? props.data[0], i, theme)}${opacity}`
    }

    if (props.stacked || props.stacked100) {
        const scales = (config.options as Record<string, unknown>).scales as Record<string, Record<string, unknown>>
        if (scales.y) {
            scales.y.stacked = true
        }
        if (scales.x) {
            scales.x.stacked = true
        }
    }

    return config
}

// ---------------------------------------------------------------------------
// Bar chart
// ---------------------------------------------------------------------------

export function buildBarConfig(props: BarProps): ChartConfiguration<'bar'> {
    const theme = mergeTheme(props.theme)
    const horizontal = props.orientation === 'horizontal'

    const datasets: ChartDataset<'bar'>[] = props.data.map((s, i) => ({
        label: s.label,
        data: s.data,
        backgroundColor: resolveColor(s, i, theme),
        borderColor: resolveColor(s, i, theme),
        borderWidth: 0,
        borderRadius: props.borderRadius ?? 4,
        hidden: s.hidden,
        _hogMeta: s.meta,
    } as ChartDataset<'bar'>))

    const yAxes = buildYAxes(props, theme, { startAtZero: true, gridLines: true })
    const opts = baseOptions(props, theme, props.data)

    return {
        type: 'bar',
        data: { labels: props.labels, datasets },
        options: {
            ...opts,
            indexAxis: horizontal ? 'y' : 'x',
            scales: {
                x: buildScaleConfig(props.xAxis, theme) as never,
                ...yAxes,
            },
            plugins: {
                ...(opts.plugins as Record<string, unknown>),
                annotation: {
                    annotations: buildGoalLineAnnotations(props.goalLines, theme),
                },
                stacked100: props.stacked100 ? { enable: true } : undefined,
                datalabels: props.showValues ? { display: true, color: theme.axisColor } : { display: false },
            },
        } as never,
    }
}

// ---------------------------------------------------------------------------
// Pie chart
// ---------------------------------------------------------------------------

export function buildPieConfig(props: PieProps): ChartConfiguration<'doughnut'> {
    const theme = mergeTheme(props.theme)
    const colors = props.data.map((d, i) => d.color ?? seriesColor(theme, i))

    return {
        type: 'doughnut',
        data: {
            labels: props.data.map((d) => d.label),
            datasets: [
                {
                    data: props.data.map((d) => d.value),
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: theme.backgroundColor === 'transparent' ? '#fff' : theme.backgroundColor,
                },
            ],
        },
        options: {
            ...baseOptions(props, theme),
            cutout: (props.donut ?? true) ? `${(props.innerRadius ?? 0.6) * 100}%` : '0%',
            plugins: {
                ...((baseOptions(props, theme) as Record<string, unknown>).plugins as Record<string, unknown>),
                datalabels:
                    props.showLabels ?? true
                        ? {
                              display: true,
                              color: '#fff',
                              formatter: (_value: number, ctx: { dataIndex: number }) => {
                                  const total = props.data.reduce((sum, d) => sum + d.value, 0)
                                  const pct = ((props.data[ctx.dataIndex].value / total) * 100).toFixed(1)
                                  return `${pct}%`
                              },
                          }
                        : { display: false },
            },
        } as never,
    }
}

// ---------------------------------------------------------------------------
// Box plot
// ---------------------------------------------------------------------------

export function buildBoxPlotConfig(props: BoxPlotProps): ChartConfiguration {
    const theme = mergeTheme(props.theme)

    return {
        type: 'boxplot' as never,
        data: {
            labels: props.data.map((d) => d.label),
            datasets: [
                {
                    data: props.data.map((d) => ({
                        min: d.min,
                        q1: d.q1,
                        median: d.median,
                        q3: d.q3,
                        max: d.max,
                        mean: d.mean,
                        outliers: d.outliers ?? [],
                    })),
                    backgroundColor: `${theme.colors[0]}40`,
                    borderColor: theme.colors[0],
                    borderWidth: 2,
                    meanBackgroundColor: theme.colors[1],
                    meanBorderColor: theme.colors[1],
                    outlierBackgroundColor: `${theme.colors[2]}80`,
                } as never,
            ],
        },
        options: {
            ...baseOptions(props, theme),
            scales: {
                x: buildScaleConfig(props.xAxis, theme) as never,
                y: buildScaleConfig(props.yAxis, theme, { gridLines: true }) as never,
            },
        } as never,
    }
}

// ---------------------------------------------------------------------------
// Lifecycle (stacked bar with fixed 4 statuses)
// ---------------------------------------------------------------------------

export function buildLifecycleConfig(props: LifecycleProps): ChartConfiguration<'bar'> {
    const theme = mergeTheme(props.theme)
    const defaultColors = {
        new: '#1AA35C',
        returning: '#1D4AFF',
        resurrecting: '#C73AC8',
        dormant: '#F04F58',
    }
    const colors = { ...defaultColors, ...props.statusColors }
    const visible = props.visibleStatuses ?? (['new', 'returning', 'resurrecting', 'dormant'] as const)

    const statuses = ['new', 'returning', 'resurrecting', 'dormant'] as const
    const datasets: ChartDataset<'bar'>[] = statuses
        .filter((s) => visible.includes(s))
        .map((status) => ({
            label: status.charAt(0).toUpperCase() + status.slice(1),
            data: props.data.map((bucket) => (status === 'dormant' ? -Math.abs(bucket[status]) : bucket[status])),
            backgroundColor: colors[status],
            borderWidth: 0,
            borderRadius: 2,
        }))

    const opts = baseOptions(props, theme)
    return {
        type: 'bar',
        data: { labels: props.labels, datasets },
        options: {
            ...opts,
            scales: {
                x: buildScaleConfig(props.xAxis, theme) as never,
                y: {
                    ...buildScaleConfig(props.yAxis, theme, { gridLines: true, startAtZero: true }),
                    stacked: true,
                } as never,
            },
            plugins: {
                ...(opts.plugins as Record<string, unknown>),
                annotation: {
                    annotations: buildGoalLineAnnotations(props.goalLines, theme),
                },
            },
        } as never,
    }
}

// ---------------------------------------------------------------------------
// Tooltip context builder — translates Chart.js tooltip model → TooltipContext
// ---------------------------------------------------------------------------

/**
 * Build a HogCharts `TooltipContext` from a Chart.js tooltip model.
 * Called by the external tooltip handler injected in `useHogChart`.
 */
export function buildTooltipContext(
    tooltipModel: {
        opacity: number
        title?: string[]
        dataPoints?: Array<{
            datasetIndex: number
            dataIndex: number
            raw: number
            dataset: { label?: string; borderColor?: string | string[]; _hogMeta?: Record<string, unknown> }
        }>
        caretX: number
        caretY: number
    },
    chartBounds: DOMRect,
    seriesData: Series[]
): TooltipContext | null {
    if (tooltipModel.opacity === 0 || !tooltipModel.dataPoints?.length) {
        return null
    }

    const points: TooltipPoint[] = tooltipModel.dataPoints.map((dp) => {
        const color = Array.isArray(dp.dataset.borderColor)
            ? dp.dataset.borderColor[dp.dataIndex]
            : (dp.dataset.borderColor ?? '#888')
        // Prefer meta from the dataset (stashed during config build), fall back to seriesData
        const meta = dp.dataset._hogMeta ?? seriesData[dp.datasetIndex]?.meta
        return {
            seriesIndex: dp.datasetIndex,
            pointIndex: dp.dataIndex,
            value: dp.raw,
            seriesLabel: dp.dataset.label ?? '',
            color,
            meta,
        }
    })

    return {
        label: tooltipModel.title?.[0] ?? '',
        points,
        position: { x: tooltipModel.caretX, y: tooltipModel.caretY },
        chartBounds,
    }
}

// ---------------------------------------------------------------------------
// Y-axis helpers (supports dual y-axes)
// ---------------------------------------------------------------------------

function buildYAxes(
    props: TimeSeriesProps,
    theme: HogChartTheme,
    defaults?: Partial<AxisConfig>
): Record<string, unknown> {
    if (Array.isArray(props.yAxis)) {
        return {
            y: {
                ...buildScaleConfig(props.yAxis[0], theme, { gridLines: true, ...defaults }),
                position: 'left',
            },
            y1: {
                ...buildScaleConfig(props.yAxis[1], theme, defaults),
                position: 'right',
                grid: { display: false },
            },
        }
    }
    return {
        y: buildScaleConfig(props.yAxis, theme, { gridLines: true, ...defaults }),
    }
}
