/* eslint-disable react/forbid-dom-props -- row sizes and positions come from props */
import React, { useMemo } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { BarChartConfig, ChartTheme, Series, TooltipContext } from '../../core/types'
import { percentage } from '../../utils/format'
import { BarChart } from '../BarChart/BarChart'
import { partValue } from '../ProportionBar/proportion-bar-data'

export interface BarListConfig {
    /** `start` (default) puts the label left of the bar and the value right of it. `top` puts the
     *  label and the value on one line above the bar, so the bar and a long label get the full width. */
    labelPosition?: 'start' | 'top'
    /** `max` (default) fills the track with the largest row, to compare the rows with each other.
     *  `total` makes the track the whole, so each bar shows its share of `total`. */
    scale?: 'max' | 'total'
    /** What the value column shows: the formatted value, its share of the total, or both as
     *  `share · value`. Default `value`. With `labelPosition: 'start'`, a list narrower than 28rem
     *  shows only the share for `both`, and the tooltip still shows the value. */
    valueDisplay?: 'value' | 'percent' | 'both'
    /** Row height in px, label line included. Default 28, or 40 with `labelPosition: 'top'`. */
    rowHeight?: number
    /** Bar thickness in px. Default 12, or 8 with `labelPosition: 'top'`. */
    barHeight?: number
    /** Corner radius in px for the bar and its track. Default 4. */
    barCornerRadius?: number
    tooltip?: {
        enabled?: boolean
    }
}

/** Shares `series` and `valueFormatter` with `PieChart` and `ProportionBar`. */
export interface BarListProps<Meta = unknown> {
    /** One series per row, valued like a `PieChart` slice: the sum of `data`, floored at 0. Rows
     *  keep the order of `series`, so sort them before you pass them in. */
    series: Series<Meta>[]
    theme: ChartTheme
    config?: BarListConfig
    /** The whole that each share is a fraction of. Defaults to the sum of the rows. Set it when the
     *  rows are the top of a larger whole, so the shares stay true to that whole. */
    total?: number
    /** Formats a row's raw value in the value column and the tooltip. */
    valueFormatter?: (value: number) => string
    /** Content of a row's label cell, for example an icon and a link. Defaults to the series label.
     *  The cell is a flex row that truncates, so wrap long text in a `truncate` element. */
    renderLabel?: (series: Series<Meta>) => React.ReactNode
    /** Replaces the default tooltip. `ctx.seriesData[0].series.meta` is the `meta` of the hovered row. */
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const DEFAULT_ROW_HEIGHT = { start: 28, top: 40 }
const DEFAULT_BAR_HEIGHT = { start: 12, top: 8 }
const TOP_LABEL_LINE_HEIGHT = 16
const TOP_LABEL_GAP = 4
const DEFAULT_CORNER_RADIUS = 4
const MIN_BAR_SIZE = 4
const BAR_SERIES_KEY = 'bar-list'

export function BarList<Meta = unknown>({ onError, ...rest }: BarListProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <BarListInner {...rest} onError={onError} />
        </ChartErrorBoundary>
    )
}

function defaultValueFormatter(value: number): string {
    return value.toLocaleString()
}

function formatShare(fraction: number): string {
    return fraction > 0 && fraction < 0.001 ? '<0.1%' : percentage(fraction, 1)
}

function BarListInner<Meta = unknown>({
    series,
    theme,
    config,
    total,
    valueFormatter = defaultValueFormatter,
    renderLabel,
    tooltip,
    dataAttr,
    onError,
}: BarListProps<Meta>): React.ReactElement | null {
    const labelPosition = config?.labelPosition ?? 'start'
    const {
        scale = 'max',
        valueDisplay = 'value',
        rowHeight = DEFAULT_ROW_HEIGHT[labelPosition],
        barHeight = DEFAULT_BAR_HEIGHT[labelPosition],
        barCornerRadius = DEFAULT_CORNER_RADIUS,
        tooltip: tooltipConfig,
    } = config ?? {}
    const isTop = labelPosition === 'top'

    const rows = useMemo(
        () =>
            series
                .map((s, index) => ({
                    series: { ...s, color: s.color || theme.colors[index % theme.colors.length] },
                    value: partValue(s),
                }))
                .filter((row) => !row.series.visibility?.excluded),
        [series, theme.colors]
    )
    const whole = total ?? rows.reduce((acc, row) => acc + row.value, 0)
    const domainMax = scale === 'total' ? whole : Math.max(0, ...rows.map((row) => row.value))

    const labels = useMemo(() => rows.map((row) => row.series.key), [rows])
    const barSeries = useMemo<Series<Meta>[]>(
        () => [
            {
                key: BAR_SERIES_KEY,
                label: '',
                data: rows.map((row) => row.value),
                bars: rows.map((row) => ({ color: row.series.color, meta: row.series.meta })),
            },
        ],
        [rows]
    )

    const barOffsetInRow = (rowHeight - barHeight) / 2
    const plotTop = isTop ? Math.max(0, TOP_LABEL_LINE_HEIGHT + TOP_LABEL_GAP - barOffsetInRow) : 0

    const barConfig = useMemo<BarChartConfig>(
        () => ({
            barLayout: 'stacked',
            axisOrientation: 'horizontal',
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            showCrosshair: false,
            margins: { top: plotTop, right: 0, bottom: 0, left: 0 },
            barCornerRadius,
            bars: {
                track: 'solid',
                bandPadding: Math.max(0, 1 - barHeight / rowHeight),
                minBandSize: 0,
                minBarSize: MIN_BAR_SIZE,
                roundStackEnds: true,
                valueDomain: { min: 0, max: domainMax > 0 ? domainMax : 1 },
            },
            tooltip: {
                enabled: tooltipConfig?.enabled !== false,
                hitArea: 'band',
                valueFormatter,
                labelFormatter: (key) => rows.find((row) => row.series.key === key)?.series.label ?? key,
            },
        }),
        [barCornerRadius, barHeight, rowHeight, plotTop, domainMax, tooltipConfig?.enabled, valueFormatter, rows]
    )

    if (rows.length === 0) {
        return null
    }

    return (
        <div
            className={isTop ? 'relative min-w-0 text-xs' : '@container grid min-w-0 items-center gap-x-3 text-xs'}
            style={
                isTop
                    ? { height: plotTop + rows.length * rowHeight }
                    : {
                          gridTemplateColumns: 'fit-content(40%) minmax(0, 1fr) auto',
                          gridTemplateRows: `repeat(${rows.length}, ${rowHeight}px)`,
                      }
            }
        >
            <div
                className={
                    isTop ? 'absolute inset-0 flex flex-col' : 'col-start-2 row-start-1 flex flex-col self-stretch'
                }
                style={isTop ? undefined : { gridRowEnd: `span ${rows.length}` }}
            >
                <BarChart
                    series={barSeries}
                    labels={labels}
                    theme={theme}
                    config={barConfig}
                    tooltip={tooltip}
                    dataAttr={dataAttr}
                    onError={onError}
                />
            </div>
            {rows.map((row, i) => (
                <div
                    key={row.series.key}
                    className={isTop ? 'absolute inset-x-0 flex h-4 items-center justify-between gap-2' : 'contents'}
                    style={
                        isTop
                            ? { top: plotTop + i * rowHeight + barOffsetInRow - TOP_LABEL_GAP - TOP_LABEL_LINE_HEIGHT }
                            : undefined
                    }
                >
                    <div className="flex min-w-0 items-center gap-1.5" title={row.series.label}>
                        {renderLabel ? renderLabel(row.series) : <span className="truncate">{row.series.label}</span>}
                    </div>
                    <div className="shrink-0 whitespace-nowrap text-right text-muted tabular-nums">
                        {valueDisplay === 'value'
                            ? valueFormatter(row.value)
                            : formatShare(whole > 0 ? row.value / whole : 0)}
                        {valueDisplay === 'both' ? (
                            <span className={isTop ? undefined : '@max-md:hidden'}> · {valueFormatter(row.value)}</span>
                        ) : null}
                    </div>
                </div>
            ))}
        </div>
    )
}
