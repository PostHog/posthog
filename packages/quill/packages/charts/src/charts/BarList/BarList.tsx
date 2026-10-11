import React, { useCallback, useMemo } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { BarChartConfig, ChartTheme, Series, TooltipContext } from '../../core/types'
import { percentage } from '../../utils/format'
import { BarChart } from '../BarChart/BarChart'
import { PieTooltip } from '../PieChart/PieTooltip'
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

/** Shares `series`, `valueFormatter` and `tooltip` with `PieChart` and `ProportionBar`. */
export interface BarListProps<Meta = unknown> {
    /** One series per row, valued like a `PieChart` slice: the sum of `data`, floored at 0. Rows
     *  keep the order of `series`, so sort them before you pass them in. */
    series: Series<Meta>[]
    theme: ChartTheme
    config?: BarListConfig
    /** The whole that each share is a fraction of. Defaults to the sum of the rows. Set it when the
     *  rows are the top of a larger whole, so the shares stay true to that whole. */
    total?: number
    /** Formats a row's raw value in the value column and the default tooltip. */
    valueFormatter?: (value: number) => string
    /** Content of a row's label cell, for example an icon and a link. Defaults to the series label.
     *  The cell is a flex row that truncates, so wrap long text in a `truncate` element. */
    renderLabel?: (series: Series<Meta>) => React.ReactNode
    /** Replaces the default tooltip. As on `PieChart`, `ctx.seriesData[0]` is the hovered row, with
     *  its raw `value` and its `fraction` of the total. */
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

interface BarListRow<Meta> {
    series: Series<Meta> & { color: string }
    index: number
    value: number
}

const DEFAULT_ROW_HEIGHT = { start: 28, top: 40 }
const DEFAULT_BAR_HEIGHT = { start: 12, top: 8 }
// The `top` label line is `h-4`, and it sits this far above its bar.
const TOP_LABEL_LINE_HEIGHT = 16
const TOP_LABEL_GAP = 4
const DEFAULT_CORNER_RADIUS = 4
// Keeps a row with a tiny share visible as a nub next to the largest row.
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

// A non-zero share must not read as 0% next to a bar that `MIN_BAR_SIZE` keeps visible.
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
}: BarListProps<Meta>): React.ReactElement {
    const labelPosition = config?.labelPosition ?? 'start'
    const {
        scale = 'max',
        valueDisplay = 'value',
        rowHeight = DEFAULT_ROW_HEIGHT[labelPosition],
        barHeight = DEFAULT_BAR_HEIGHT[labelPosition],
        barCornerRadius = DEFAULT_CORNER_RADIUS,
        tooltip: tooltipConfig,
    } = config ?? {}

    const rows = useMemo<BarListRow<Meta>[]>(
        () =>
            series
                .map((s, index) => ({
                    series: { ...s, color: s.color || theme.colors[index % theme.colors.length] },
                    index,
                    value: partValue(s),
                }))
                .filter((row) => !row.series.visibility?.excluded),
        [series, theme.colors]
    )
    const whole = useMemo(() => total ?? rows.reduce((acc, row) => acc + row.value, 0), [total, rows])
    const fractionOf = useCallback((value: number): number => (whole > 0 ? value / whole : 0), [whole])
    const domainMax = useMemo(
        () => (scale === 'total' ? whole : Math.max(0, ...rows.map((row) => row.value))),
        [scale, whole, rows]
    )

    // One series with a per-bar color, so every row is its own band and keeps its own color.
    const labels = useMemo(() => rows.map((row) => row.series.key), [rows])
    const barSeries = useMemo<Series<Meta>[]>(
        () => [
            {
                key: BAR_SERIES_KEY,
                label: '',
                data: rows.map((row) => row.value),
                bars: rows.map((row) => ({ color: row.series.color, label: row.series.label, meta: row.series.meta })),
            },
        ],
        [rows]
    )

    // Each bar is centered in its row, so a `top` label line fits in the space above the bar. When that
    // space is too small for the first row's label, the plot moves down by the difference.
    const barOffsetInRow = (rowHeight - barHeight) / 2
    const plotTop = labelPosition === 'top' ? Math.max(0, TOP_LABEL_LINE_HEIGHT + TOP_LABEL_GAP - barOffsetInRow) : 0

    // A one-series stacked layout makes the bar exactly `barHeight` thick. The grouped layout insets
    // each bar inside its band, and the band padding then no longer maps to a thickness in px.
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
                // The band step is `rowHeight` because the outer padding is half the inner padding, so
                // each band lines up with its label and value cells.
                bandPadding: Math.max(0, 1 - barHeight / rowHeight),
                minBandSize: 0,
                minBarSize: MIN_BAR_SIZE,
                roundStackEnds: true,
                valueDomain: { min: 0, max: domainMax > 0 ? domainMax : 1 },
            },
            // `band` so a row reports its tooltip over its track too, not only over its painted bar.
            tooltip: { enabled: tooltipConfig?.enabled !== false, hitArea: 'band' },
        }),
        [barCornerRadius, barHeight, rowHeight, plotTop, domainMax, tooltipConfig?.enabled]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<Meta>): React.ReactNode => {
            const row = rows[ctx.dataIndex]
            if (!row) {
                return null
            }
            const rowCtx = {
                ...ctx,
                label: row.series.label,
                dataIndex: row.index,
                seriesData: [
                    {
                        ...ctx.seriesData[0],
                        series: row.series,
                        color: row.series.color,
                        value: row.value,
                        fraction: fractionOf(row.value),
                    },
                ],
            }
            return tooltip ? tooltip(rowCtx) : <PieTooltip ctx={rowCtx} valueFormatter={valueFormatter} />
        },
        [rows, tooltip, fractionOf, valueFormatter]
    )

    const renderLabelContent = (row: BarListRow<Meta>): React.ReactNode =>
        renderLabel ? renderLabel(row.series) : <span className="truncate">{row.series.label}</span>
    const renderValueContent = (row: BarListRow<Meta>): React.ReactNode => (
        <>
            {valueDisplay === 'value' ? valueFormatter(row.value) : formatShare(fractionOf(row.value))}
            {valueDisplay === 'both' ? (
                // A narrow `start` list drops the value and keeps the share, so the bar keeps its room.
                <span className={labelPosition === 'start' ? '@max-md:hidden' : undefined}>
                    {' '}
                    · {valueFormatter(row.value)}
                </span>
            ) : null}
        </>
    )
    const chart =
        rows.length > 0 ? (
            <BarChart
                series={barSeries}
                labels={labels}
                theme={theme}
                config={barConfig}
                tooltip={renderTooltip}
                dataAttr={dataAttr}
                onError={onError}
            />
        ) : null

    if (labelPosition === 'top') {
        // The chart fills the list, and each label line sits on top of it, just above its bar.
        return (
            <div
                className="relative min-w-0 text-xs"
                // eslint-disable-next-line react/forbid-dom-props -- height comes from the row count
                style={{ height: plotTop + rows.length * rowHeight }}
            >
                <div className="absolute inset-0 flex flex-col">{chart}</div>
                {rows.map((row, i) => (
                    <div
                        key={row.series.key}
                        className="absolute inset-x-0 flex h-4 items-center justify-between gap-2"
                        // eslint-disable-next-line react/forbid-dom-props -- position comes from the row index
                        style={{
                            top: plotTop + i * rowHeight + barOffsetInRow - TOP_LABEL_GAP - TOP_LABEL_LINE_HEIGHT,
                        }}
                    >
                        <div className="flex min-w-0 items-center gap-1.5" title={row.series.label}>
                            {renderLabelContent(row)}
                        </div>
                        <div className="shrink-0 whitespace-nowrap text-muted tabular-nums">
                            {renderValueContent(row)}
                        </div>
                    </div>
                ))}
            </div>
        )
    }

    // The label and value columns size to their content, and the bar column takes the rest. Each
    // row is `rowHeight` tall, and so is each band of the chart that spans the bar column.
    return (
        <div
            className="@container grid min-w-0 items-center gap-x-3 text-xs"
            // eslint-disable-next-line react/forbid-dom-props -- row count and height come from props
            style={{
                gridTemplateColumns: 'fit-content(40%) minmax(0, 1fr) auto',
                gridTemplateRows: `repeat(${rows.length}, ${rowHeight}px)`,
            }}
        >
            {rows.map((row, i) => (
                <React.Fragment key={row.series.key}>
                    <div
                        className="flex min-w-0 items-center gap-1.5 col-start-1"
                        // eslint-disable-next-line react/forbid-dom-props -- row position comes from data
                        style={{ gridRow: i + 1 }}
                        title={row.series.label}
                    >
                        {renderLabelContent(row)}
                    </div>
                    <div
                        className="col-start-3 whitespace-nowrap text-right text-muted tabular-nums"
                        // eslint-disable-next-line react/forbid-dom-props -- row position comes from data
                        style={{ gridRow: i + 1 }}
                    >
                        {renderValueContent(row)}
                    </div>
                </React.Fragment>
            ))}
            {chart ? (
                <div
                    className="col-start-2 row-start-1 flex flex-col self-stretch"
                    // eslint-disable-next-line react/forbid-dom-props -- spans every row
                    style={{ gridRowEnd: `span ${rows.length}` }}
                >
                    {chart}
                </div>
            ) : null}
        </div>
    )
}
