import type { ChartConfiguration, ChartDataset } from 'chart.js'

import { createXAxisTickCallback } from 'lib/charts/utils/dates'

import type { AreaProps, LineProps } from '../types'
import { mergeTheme } from '../utils/theme'
import {
    baseOptions,
    buildGoalLineAnnotations,
    buildScaleConfig,
    buildYAxes,
    crosshairConfig,
    resolveColor,
    resolveLineStyle,
    resolvePointRadius,
    statusSegment,
} from './common'

/** Regex check for ISO date prefix like `2024-01-15` or `2024-01-15T...`. */
function looksLikeDate(value: string | number): boolean {
    return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)
}

export function buildLineConfig(props: LineProps): ChartConfiguration<'line'> {
    const theme = mergeTheme(props.theme)
    const opts_ = props.options ?? {}
    const maxSeries = opts_.maxSeries ?? Infinity
    const seriesData = props.series.slice(0, maxSeries)
    const isArea = opts_.isArea ?? false
    const fillOpacity = opts_.fillOpacity ?? 0.5
    const stacked = opts_.stacked ?? false
    const percentStacked = opts_.percentStacked ?? false
    const highlightIdx = props.highlightSeriesIndex ?? null

    // Derive labels from x-values of the first series
    const labels = (props.series[0]?.data ?? []).map((d) => String(d.x))

    const datasets: ChartDataset<'line'>[] = seriesData.map((s, i) => {
        let data = s.data.map((d) => d.y)
        if (opts_.cumulative) {
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
            const hex = Math.round(fillOpacity * 255)
                .toString(16)
                .padStart(2, '0')
            bgColor = `${color}${hex}`
        } else {
            bgColor = `${color}18`
        }

        const borderDash = resolveLineStyle(s.lineStyle)
        const segment = statusSegment(s.data)

        let yAxisID = 'y'
        if (s.yAxisPosition === 'right') {
            yAxisID = 'y1'
        }

        return {
            label: s.label,
            data,
            borderColor: isDimmed ? `${color}55` : color,
            backgroundColor: bgColor,
            borderWidth: opts_.lineWidth ?? 2,
            borderDash,
            pointRadius: resolvePointRadius(opts_.showDots, data.length),
            pointHoverRadius: 5,
            tension: opts_.interpolation === 'smooth' ? 0.35 : 0,
            stepped: opts_.interpolation === 'step' ? 'before' : false,
            hidden: s.hidden,
            fill: shouldFill ? (stacked || percentStacked ? 'origin' : true) : false,
            yAxisID,
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
                data: cs.data.map((d) => d.y),
                borderColor: `${resolveColor(cs, datasets.length, theme)}60`,
                backgroundColor: 'transparent',
                borderWidth: (opts_.lineWidth ?? 2) - 0.5,
                borderDash: [6, 4],
                pointRadius: 0,
                hidden: cs.hidden,
                fill: false,
                _hogMeta: cs.meta,
            } as ChartDataset<'line'>)
        }
    }

    const yAxes = buildYAxes(props, theme)
    const baseOpts = baseOptions(props, theme, seriesData)

    const showCrosshair = opts_.crosshair ?? true
    const crosshairPluginConfig = crosshairConfig(showCrosshair, theme.axisColor)

    const xScale = buildScaleConfig(props.xAxis, theme)

    // Auto-detect dates from x-values and set up tick formatting
    const firstX = props.series[0]?.data?.[0]?.x
    const hasDates = firstX !== undefined && looksLikeDate(firstX)
    const tickCallback = hasDates
        ? createXAxisTickCallback({
              interval: props.interval ?? 'day',
              allDays: (props.series[0]?.data ?? []).map((d) => d.x),
              timezone: 'UTC',
          })
        : undefined
    if (tickCallback) {
        const ticks = (xScale as Record<string, Record<string, unknown>>).ticks
        ticks.callback = tickCallback
        ticks.maxRotation = 0
        ticks.autoSkipPadding = 20
    }
    if (opts_.hideXAxis) {
        ;(xScale as Record<string, unknown>).display = false
    }
    if (stacked || percentStacked) {
        ;(xScale as Record<string, unknown>).stacked = true
    }

    if (stacked || percentStacked) {
        for (const key of Object.keys(yAxes)) {
            ;(yAxes as Record<string, Record<string, unknown>>)[key].stacked = true
        }
    }
    if (opts_.hideYAxis) {
        for (const key of Object.keys(yAxes)) {
            ;(yAxes as Record<string, Record<string, unknown>>)[key].display = false
        }
    }

    const chartConfig = {
        type: 'line' as const,
        data: { labels, datasets },
        options: {
            ...baseOpts,
            scales: {
                x: xScale as never,
                ...yAxes,
            },
            plugins: {
                ...baseOpts.plugins,
                ...crosshairPluginConfig,
                annotation: {
                    annotations: buildGoalLineAnnotations(props.goalLines, theme),
                },
                stacked100: percentStacked ? { enable: true, precision: 1 } : undefined,
                datalabels: opts_.showValues ? { display: true, color: theme.axisColor } : { display: false },
            },
        } as never,
    }
    return chartConfig
}

export function buildAreaConfig(props: AreaProps): ChartConfiguration<'line'> {
    return buildLineConfig({
        ...props,
        options: {
            ...props.options,
            isArea: true,
            fillOpacity: props.options?.fillOpacity ?? 0.1,
        },
    })
}
