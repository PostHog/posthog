import React, { useMemo } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useResolvedChartTheme } from '../../core/theme'
import type { ChartTheme, Series, TooltipContext } from '../../core/types'
import { partValue } from '../ProportionBar/proportion-bar-data'
import { BarListLabel } from './BarListLabel'
import { BarListValue } from './BarListValue'
import { StackedBarList, type StackedBarListConfig } from './StackedBarList'

export interface BarListConfig extends Omit<StackedBarListConfig, 'valueDomain' | 'tooltip'> {
    /** `max` (default) fills the track with the largest row, to compare the rows with each other.
     *  `total` makes the track the whole, so each bar shows its share of `total`. */
    scale?: 'max' | 'total'
    /** What the value column shows: the formatted value, its share of the total, or both as
     *  `share · value`. Default `value`. With `labelPosition: 'start'`, a list narrower than 28rem
     *  shows only the share for `both`, and the tooltip still shows the value. */
    valueDisplay?: 'value' | 'percent' | 'both'
    tooltip?: {
        enabled?: boolean
    }
}

/** Shares `series` and `valueFormatter` with `PieChart` and `ProportionBar`. */
export interface BarListProps<Meta = unknown> {
    /** One series per row, valued like a `PieChart` slice: the sum of `data`, floored at 0. Rows
     *  keep the order of `series`, so sort them before you pass them in. */
    series: Series<Meta>[]
    /** Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars. */
    theme?: ChartTheme
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

function BarListInner<Meta = unknown>({
    series,
    theme: themeProp,
    config,
    total,
    valueFormatter = defaultValueFormatter,
    renderLabel,
    tooltip,
    dataAttr,
    onError,
}: BarListProps<Meta>): React.ReactElement | null {
    const theme = useResolvedChartTheme(themeProp)
    const { scale = 'max', valueDisplay = 'value', labelPosition = 'start' } = config ?? {}

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

    const stackedConfig = useMemo<StackedBarListConfig>(
        () => ({
            labelPosition,
            rowHeight: config?.rowHeight,
            barHeight: config?.barHeight,
            barCornerRadius: config?.barCornerRadius,
            valueDomain: { min: 0, max: domainMax > 0 ? domainMax : 1 },
            tooltip: {
                enabled: config?.tooltip?.enabled,
                valueFormatter,
                labelFormatter: (key) => rows.find((row) => row.series.key === key)?.series.label ?? key,
            },
        }),
        [
            labelPosition,
            config?.rowHeight,
            config?.barHeight,
            config?.barCornerRadius,
            config?.tooltip?.enabled,
            domainMax,
            valueFormatter,
            rows,
        ]
    )

    if (rows.length === 0) {
        return null
    }

    return (
        <StackedBarList
            labels={labels}
            series={barSeries}
            theme={theme}
            config={stackedConfig}
            renderLabel={(rowIndex) => <BarListLabel series={rows[rowIndex].series} renderLabel={renderLabel} />}
            renderValue={(rowIndex) => (
                <BarListValue
                    value={rows[rowIndex].value}
                    whole={whole}
                    valueDisplay={valueDisplay}
                    labelPosition={labelPosition}
                    valueFormatter={valueFormatter}
                />
            )}
            tooltip={tooltip}
            dataAttr={dataAttr}
            onError={onError}
        />
    )
}
