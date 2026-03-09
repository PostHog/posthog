import type { ChartOptions } from 'chart.js'

import type {
    AxisConfig,
    BaseChartProps,
    GoalLine,
    HogChartTheme,
    Series,
    TimeSeriesProps,
    TooltipContext,
    TooltipPoint,
} from '../types'
import { formatValue } from '../utils/format'
import { seriesColor } from '../utils/theme'

export interface TooltipCallbacks {
    onShow: (context: TooltipContext) => void
    onHide: () => void
}

export function resolveColor(series: Series, index: number, theme: HogChartTheme): string {
    return series.color ?? seriesColor(theme, index)
}

function chartBaseOptions(): ChartOptions {
    return {
        responsive: true,
        maintainAspectRatio: false,
        elements: {
            line: { tension: 0 },
        },
    }
}

export function crosshairConfig(enabled: boolean, crosshairColor: string | null | undefined): Record<string, unknown> {
    if (!enabled) {
        return { crosshair: false }
    }
    return {
        crosshair: {
            snap: { enabled: true },
            sync: { enabled: false },
            zoom: { enabled: false },
            line: { color: crosshairColor ?? undefined, width: 1 },
        },
    }
}

export function incompleteSegment(
    dataLength: number,
    count: number
): { borderDash: (ctx: { p1DataIndex: number }) => number[] | undefined } | undefined {
    if (count <= 0) {
        return undefined
    }
    const startIndex = dataLength - count
    return {
        borderDash: (ctx: { p1DataIndex: number }) => (ctx.p1DataIndex >= startIndex ? [10, 10] : undefined),
    }
}

export function buildScaleConfig(
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
        type: merged.scale === 'logarithmic' ? 'logarithmic' : merged.scale === 'linear' ? 'linear' : undefined,
    }
}

export function buildGoalLineAnnotations(
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

export interface HogTooltipMeta {
    seriesData: Series[]
    theme: HogChartTheme
}

export type BaseChartOptions = ChartOptions & {
    _hogTooltipMeta: HogTooltipMeta
}

export function baseOptions(props: BaseChartProps, theme: HogChartTheme, seriesData?: Series[]): BaseChartOptions {
    const hasCustomTooltip = !!props.tooltip?.render
    const shared = props.tooltip?.shared ?? true

    return {
        ...chartBaseOptions(),
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
                position: (props.legend?.position !== 'none' ? props.legend?.position : undefined) ?? 'bottom',
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

export function buildYAxes(
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

export function resolvePointRadius(showDots: boolean | 'auto' | undefined, pointCount: number): number {
    if (showDots === true) {
        return 3
    }
    if (showDots === false) {
        return 0
    }
    if (pointCount === 1) {
        return 4
    }
    return pointCount <= 30 ? 3 : 0
}

export function resolveLineStyle(style: 'solid' | 'dashed' | 'dotted' | undefined): number[] | undefined {
    if (style === 'dashed') {
        return [6, 4]
    }
    if (style === 'dotted') {
        return [2, 4]
    }
    return undefined
}

export function buildTooltipContext(
    tooltipModel: {
        opacity: number
        title?: string[]
        dataPoints?: Array<{
            datasetIndex: number
            dataIndex: number
            raw: number
            dataset: {
                label?: string
                borderColor?: string | string[]
                _hogMeta?: Record<string, unknown>
                _hogHideFromTooltip?: boolean
            }
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
