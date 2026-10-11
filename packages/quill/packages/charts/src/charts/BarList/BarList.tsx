import React, { useCallback, useMemo } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { ChartTheme, Series, TooltipContext } from '../../core/types'
import { percentage } from '../../utils/format'
import { PieTooltip } from '../PieChart/PieTooltip'
import { partValue } from '../ProportionBar/proportion-bar-data'
import { StackedBarList, type StackedBarListConfig } from './StackedBarList'

export interface BarListConfig extends Omit<StackedBarListConfig, 'valueDomain'> {
    /** `max` (default) fills the track with the largest row, to compare the rows with each other.
     *  `total` makes the track the whole, so each bar shows its share of `total`. */
    scale?: 'max' | 'total'
    /** What the value column shows: the formatted value, its share of the total, or both as
     *  `share · value`. Default `value`. With `labelPosition: 'start'`, a list narrower than 28rem
     *  shows only the share for `both`, and the tooltip still shows the value. */
    valueDisplay?: 'value' | 'percent' | 'both'
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

// A non-zero share must not read as 0% next to a bar that the minimum bar size keeps visible.
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
    const { scale = 'max', valueDisplay = 'value', labelPosition = 'start' } = config ?? {}

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
    const stackedConfig = useMemo<StackedBarListConfig>(
        () => ({
            labelPosition,
            rowHeight: config?.rowHeight,
            barHeight: config?.barHeight,
            barCornerRadius: config?.barCornerRadius,
            tooltip: config?.tooltip,
            valueDomain: { min: 0, max: domainMax > 0 ? domainMax : 1 },
        }),
        [labelPosition, config?.rowHeight, config?.barHeight, config?.barCornerRadius, config?.tooltip, domainMax]
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

    const renderRowLabel = (rowIndex: number): React.ReactNode => {
        const row = rows[rowIndex]
        return (
            <span className="flex min-w-0 items-center gap-1.5" title={row.series.label}>
                {renderLabel ? renderLabel(row.series) : <span className="truncate">{row.series.label}</span>}
            </span>
        )
    }
    const renderRowValue = (rowIndex: number): React.ReactNode => {
        const row = rows[rowIndex]
        return (
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
    }

    return (
        <StackedBarList
            labels={labels}
            series={barSeries}
            theme={theme}
            config={stackedConfig}
            renderLabel={renderRowLabel}
            renderValue={renderRowValue}
            tooltip={renderTooltip}
            dataAttr={dataAttr}
            onError={onError}
        />
    )
}
