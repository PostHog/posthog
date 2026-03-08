import type { ChartConfiguration, ChartDataset } from 'chart.js'

import { createXAxisTickCallback } from '../formatXAxisTick'
import { mergeTheme } from '../theme'
import type { AreaProps, LineProps } from '../types'

import {
    baseOptions,
    buildGoalLineAnnotations,
    buildScaleConfig,
    buildYAxes,
    crosshairConfig,
    incompleteSegment,
    resolveColor,
    resolveLineStyle,
    resolvePointRadius,
} from './common'

export function buildLineConfig(props: LineProps): ChartConfiguration<'line'> {
    const theme = mergeTheme(props.theme)
    const maxSeries = props.maxSeries ?? Infinity
    const seriesData = props.data.slice(0, maxSeries)
    const isArea = props.isArea ?? false
    const fillOpacity = props.fillOpacity ?? 0.5
    const stacked = props.stacked ?? false
    const percentStacked = props.percentStacked ?? false
    const incompletePoints = props.incompletePoints ?? 0
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

        const borderDash = resolveLineStyle(s.lineStyle)
        const segment = incompleteSegment(data.length, incompletePoints)

        let yAxisID = 'y'
        if (s.yAxisPosition === 'right') {
            yAxisID = 'y1'
        }

        const isBarDisplay = s.displayType === 'bar'

        return {
            label: s.label,
            data,
            borderColor: isDimmed ? `${color}55` : color,
            backgroundColor: bgColor,
            borderWidth: isBarDisplay ? 0 : (props.lineWidth ?? 2),
            borderDash,
            pointRadius: resolvePointRadius(props.showDots, data.length),
            pointHoverRadius: 5,
            tension: props.interpolation === 'smooth' ? 0.35 : 0,
            stepped: props.interpolation === 'step' ? 'before' : false,
            hidden: s.hidden,
            fill: shouldFill ? (stacked || percentStacked ? 'origin' : true) : false,
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
    const crosshairPluginConfig = crosshairConfig(showCrosshair, theme.axisColor)

    const xScale = buildScaleConfig(props.xAxis, theme)
    const tickCallback =
        props.xAxisTickCallback ??
        (props.dates?.length
            ? createXAxisTickCallback({
                  interval: props.interval ?? 'day',
                  dates: props.dates,
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
    if (stacked || percentStacked) {
        ;(xScale as Record<string, unknown>).stacked = true
    }

    if (stacked || percentStacked) {
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
                stacked100: percentStacked ? { enable: true, precision: 1 } : undefined,
                datalabels: props.showValues ? { display: true, color: theme.axisColor } : { display: false },
            },
        } as never,
    }
    return chartConfig
}

export function buildAreaConfig(props: AreaProps): ChartConfiguration<'line'> {
    return buildLineConfig({
        ...props,
        isArea: true,
        fillOpacity: props.fillOpacity ?? 0.1,
    })
}
