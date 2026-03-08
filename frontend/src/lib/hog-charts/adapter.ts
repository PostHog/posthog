import type { ChartConfiguration, ChartDataset } from 'chart.js'

import { formatValue } from './format'
import { createXAxisTickCallback } from './formatXAxisTick'
import {
    chartBaseOptions,
    crosshairConfig as buildCrosshairPluginConfig,
    incompletenessSegment,
} from './shared'
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

export interface TooltipCallbacks {
    onShow: (context: TooltipContext) => void
    onHide: () => void
}

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
        type: merged.scale === 'logarithmic' ? 'logarithmic' : merged.scale === 'linear' ? 'linear' : 'category',
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

    const base = chartBaseOptions()
    return {
        ...base,
        animation: props.animate ? undefined : false,
        interaction: {
            includeInvisible: true,
        },
        hover: {
            mode: shared ? 'index' : 'nearest',
            axis: 'x',
            intersect: false,
        },
        plugins: {
            legend: {
                display: (props.legend?.position ?? 'none') !== 'none',
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
                                    enabled: false,
                      mode: shared ? 'index' : 'nearest',
                      intersect: !shared,
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
        _hogTooltipMeta: {
            seriesData: seriesData ?? [],
            theme,
        },
    }
}

export function buildLineConfig(props: LineProps): ChartConfiguration<'line'> {
    const theme = mergeTheme(props.theme)
    const maxSeries = props.maxSeries ?? Infinity
    const seriesData = props.data.slice(0, maxSeries)
    const isArea = props.isArea ?? false
    const fillOpacity = props.fillOpacity ?? 0.5
    const stacked = props.stacked ?? false
    const stacked100 = props.stacked100 ?? false
    const incompletenessOffset = props.incompletenessOffset ?? 0
    const highlightIdx = props.highlightSeriesIndex ?? null

    const datasets: ChartDataset<'line'>[] = seriesData.map((s, i) => {
        let data = s.data
        if (props.cumulative) {
            let sum = 0
            data = data.map((v) => (sum += v))
        }

        const color = resolveColor(s, i, theme)
        const isDimmed = highlightIdx !== null && i !== highlightIdx

        const shouldFill = s.fill ?? isArea
        let bgColor: string
        if (isDimmed) {
            bgColor = `${color}33`
        } else if (shouldFill) {
            const hex = Math.round(fillOpacity * 255).toString(16).padStart(2, '0')
            bgColor = `${color}${hex}`
        } else {
            bgColor = `${color}18`
        }

        const borderDash = s.borderDash
        const segment = incompletenessSegment(data.length, incompletenessOffset)

        let yAxisID = 'y'
        if (s.yAxisPosition === 'right') {
            yAxisID = 'y1'
        }

        return {
            label: s.label,
            data,
            borderColor: isDimmed ? `${color}55` : color,
            backgroundColor: bgColor,
            borderWidth: s.borderWidth ?? props.lineWidth ?? 2,
            borderDash,
            pointRadius: s.pointRadius ?? resolvePointRadius(props.showDots, seriesData[0]?.data.length ?? 0),
            pointHoverRadius: 5,
            tension: props.interpolation === 'smooth' ? 0.35 : 0,
            stepped: props.interpolation === 'step' ? 'before' : false,
            hidden: s.hidden,
            fill: shouldFill ? (stacked || stacked100 ? 'origin' : true) : false,
            yAxisID,
            type: s.displayType === 'bar' ? 'bar' : undefined,
            segment: segment ? { borderDash: segment.borderDash } : undefined,
            _hogMeta: s.meta,
            _hogHideFromTooltip: s.hideFromTooltip,
            ...(s.trendLine
                ? {
                      trendlineLinear: {
                          colorMin: `${color}99`,
                          colorMax: `${color}99`,
                          lineStyle: 'dotted',
                          width: 2,
                      },
                  }
                : {}),
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
                _hogMeta: cs.meta,
            } as ChartDataset<'line'>)
        }
    }

    const yAxes = buildYAxes(props, theme)
    const opts = baseOptions(props, theme, seriesData)

    const showCrosshair = props.crosshair ?? !seriesData.some((s) => s.displayType === 'bar')
    const crosshairPluginConfig = buildCrosshairPluginConfig(showCrosshair, theme.axisColor)

    const xScale = buildScaleConfig(props.xAxis, theme)
    const tickCallback =
        props.xAxisTickCallback ??
        (props.days?.length
            ? createXAxisTickCallback({
                  interval: props.interval ?? 'day',
                  allDays: props.days,
                  timezone: props.timezone ?? 'UTC',
              })
            : undefined)
    if (tickCallback) {
        const ticks = (xScale as Record<string, Record<string, unknown>>).ticks
        ticks.callback = tickCallback
        ticks.maxRotation = 0
        ticks.autoSkipPadding = 20
    }
    if (props.hideXAxis) {
        ;(xScale as Record<string, unknown>).display = false
    }
    if (stacked || stacked100) {
        ;(xScale as Record<string, unknown>).stacked = true
    }

    if (stacked || stacked100) {
        for (const key of Object.keys(yAxes)) {
            ;(yAxes as Record<string, Record<string, unknown>>)[key].stacked = true
        }
    }
    if (props.hideYAxis) {
        for (const key of Object.keys(yAxes)) {
            ;(yAxes as Record<string, Record<string, unknown>>)[key].display = false
        }
    }

    const chartConfig = {
        type: 'line' as const,
        data: { labels: props.labels, datasets },
        options: {
            ...opts,
            scales: {
                x: xScale as never,
                ...yAxes,
            },
            plugins: {
                ...(opts.plugins as Record<string, unknown>),
                ...crosshairPluginConfig,
                annotation: {
                    annotations: buildGoalLineAnnotations(props.goalLines, theme),
                },
                stacked100: stacked100 ? { enable: true, precision: 1 } : undefined,
                datalabels: props.showValues ? { display: true, color: theme.axisColor } : { display: false },
            },
        } as never,
    }
    return chartConfig
}

function resolvePointRadius(showDots: boolean | 'auto' | undefined, pointCount: number): number {
    if (showDots === true) {
        return 3
    }
    if (showDots === false) {
        return 0
    }
    return pointCount <= 30 ? 3 : 0
}

export function buildAreaConfig(props: AreaProps): ChartConfiguration<'line'> {
    return buildLineConfig({
        ...props,
        isArea: true,
        fillOpacity: props.fillOpacity ?? 0.1,
    })
}

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

export function buildTooltipContext(
    tooltipModel: {
        opacity: number
        title?: string[]
        dataPoints?: Array<{
            datasetIndex: number
            dataIndex: number
            raw: number
            dataset: { label?: string; borderColor?: string | string[]; _hogMeta?: Record<string, unknown>; _hogHideFromTooltip?: boolean }
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

    const points: TooltipPoint[] = tooltipModel.dataPoints
        .filter((dp) => {
            const dataset = dp.dataset as { _hogHideFromTooltip?: boolean }
            if (dataset._hogHideFromTooltip) {
                return false
            }
            const seriesDatum = seriesData[dp.datasetIndex]
            if (seriesDatum?.hideFromTooltip) {
                return false
            }
            return true
        })
        .map((dp) => {
            const color = Array.isArray(dp.dataset.borderColor)
                ? dp.dataset.borderColor[dp.dataIndex]
                : (dp.dataset.borderColor ?? '#888')
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
