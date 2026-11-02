/* eslint-disable react/forbid-dom-props -- row sizes and positions come from props */
import React, { useMemo } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useResolvedChartTheme } from '../../core/theme'
import type {
    BarChartConfig,
    ChartTheme,
    PointClickData,
    Series,
    TooltipConfig,
    TooltipContext,
    ValueDomain,
} from '../../core/types'
import { BarChart } from '../BarChart/BarChart'

export interface StackedBarListConfig {
    /** `start` (default) puts the label left of the bar. `top` puts the label and value on a line above it. */
    labelPosition?: 'start' | 'top'
    /** Row height in px, label line included. Default 28, or 40 with `labelPosition: 'top'`. */
    rowHeight?: number
    /** Bar thickness in px. Default 12, or 8 with `labelPosition: 'top'`. */
    barHeight?: number
    /** Corner radius in px for the bar and its track. Default 4. */
    barCornerRadius?: number
    /** Value-axis domain. Defaults to 0 up to the largest row total. */
    valueDomain?: ValueDomain
    tooltip?: Pick<TooltipConfig, 'enabled' | 'valueFormatter' | 'labelFormatter'>
}

export interface StackedBarListProps<Meta = unknown> {
    /** One row per label. Labels must be unique. */
    labels: string[]
    /** Stacked segments: `data[i]` is the value in row `i`, and `trackData[i]` caps that row's track. */
    series: Series<Meta>[]
    /** Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars. */
    theme?: ChartTheme
    config?: StackedBarListConfig
    /** Wrap long text in a `truncate` element. */
    renderLabel: (rowIndex: number) => React.ReactNode
    renderValue: (rowIndex: number) => React.ReactNode
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
    children?: React.ReactNode
}

const DEFAULT_ROW_HEIGHT = { start: 28, top: 40 }
const DEFAULT_BAR_HEIGHT = { start: 12, top: 8 }
const DEFAULT_CORNER_RADIUS = 4
// Keeps a tiny row visible as a nub.
const MIN_BAR_SIZE = 4
// Matches the label line's `h-4` class.
const TOP_LABEL_LINE_HEIGHT = 16
const TOP_LABEL_GAP = 4

export function StackedBarList<Meta = unknown>({ onError, ...rest }: StackedBarListProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <StackedBarListInner {...rest} onError={onError} />
        </ChartErrorBoundary>
    )
}

function StackedBarListInner<Meta = unknown>({
    labels,
    series,
    theme: themeProp,
    config,
    renderLabel,
    renderValue,
    tooltip,
    onPointClick,
    dataAttr,
    onError,
    children,
}: StackedBarListProps<Meta>): React.ReactElement {
    const theme = useResolvedChartTheme(themeProp)
    const labelPosition = config?.labelPosition ?? 'start'
    const {
        rowHeight = DEFAULT_ROW_HEIGHT[labelPosition],
        barHeight = DEFAULT_BAR_HEIGHT[labelPosition],
        barCornerRadius = DEFAULT_CORNER_RADIUS,
        valueDomain,
        tooltip: tooltipConfig,
    } = config ?? {}

    const resolvedValueDomain = useMemo<ValueDomain>(() => {
        if (valueDomain) {
            return valueDomain
        }
        const rowTotals = labels.map((_, row) =>
            series.reduce((acc, s) => (s.visibility?.excluded ? acc : acc + Math.max(0, s.data[row] || 0)), 0)
        )
        const max = Math.max(0, ...rowTotals)
        return { min: 0, max: max > 0 ? max : 1 }
    }, [valueDomain, labels, series])

    const barOffsetInRow = (rowHeight - barHeight) / 2
    // Moves the plot down when the first row's label does not fit above its bar.
    const plotTop = labelPosition === 'top' ? Math.max(0, TOP_LABEL_LINE_HEIGHT + TOP_LABEL_GAP - barOffsetInRow) : 0

    // Stacked, because grouped insets each bar in its band and `barHeight` would no longer be exact.
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
                // Makes each band `rowHeight` tall so it lines up with its label and value cells.
                bandPadding: Math.max(0, 1 - barHeight / rowHeight),
                minBandSize: 0,
                minBarSize: MIN_BAR_SIZE,
                roundStackEnds: true,
                valueDomain: resolvedValueDomain,
            },
            // Shows the tooltip over the track too, not only over the bar.
            tooltip: { ...tooltipConfig, enabled: tooltipConfig?.enabled !== false, hitArea: 'band' },
        }),
        [barCornerRadius, barHeight, rowHeight, plotTop, resolvedValueDomain, tooltipConfig]
    )

    const chart =
        labels.length > 0 ? (
            <BarChart
                series={series}
                labels={labels}
                theme={theme}
                config={barConfig}
                tooltip={tooltip}
                onPointClick={onPointClick}
                dataAttr={dataAttr}
                onError={onError}
            >
                {children}
            </BarChart>
        ) : null

    if (labelPosition === 'top') {
        return (
            <div className="relative min-w-0 text-xs" style={{ height: plotTop + labels.length * rowHeight }}>
                <div className="absolute inset-0 flex flex-col">{chart}</div>
                {labels.map((label, i) => (
                    <div
                        key={label}
                        className="absolute inset-x-0 flex h-4 items-center justify-between gap-2"
                        style={{
                            top: plotTop + i * rowHeight + barOffsetInRow - TOP_LABEL_GAP - TOP_LABEL_LINE_HEIGHT,
                        }}
                    >
                        <div className="flex min-w-0 items-center gap-1.5">{renderLabel(i)}</div>
                        <div
                            className="shrink-0 whitespace-nowrap text-(--color-graph-axis-label) tabular-nums"
                            translate="no"
                        >
                            {renderValue(i)}
                        </div>
                    </div>
                ))}
            </div>
        )
    }

    return (
        <div
            className="@container grid min-w-0 items-center gap-x-3 text-xs"
            style={{
                gridTemplateColumns: 'fit-content(min(40%, 12rem)) minmax(0, 1fr) auto',
                gridTemplateRows: `repeat(${labels.length}, ${rowHeight}px)`,
            }}
        >
            {labels.map((label, i) => (
                <React.Fragment key={label}>
                    <div className="flex min-w-0 items-center gap-1.5 col-start-1" style={{ gridRow: i + 1 }}>
                        {renderLabel(i)}
                    </div>
                    <div
                        className="col-start-3 whitespace-nowrap text-right text-(--color-graph-axis-label) tabular-nums"
                        style={{ gridRow: i + 1 }}
                        translate="no"
                    >
                        {renderValue(i)}
                    </div>
                </React.Fragment>
            ))}
            {chart ? (
                <div
                    className="col-start-2 row-start-1 flex flex-col self-stretch"
                    style={{ gridRowEnd: `span ${labels.length}` }}
                >
                    {chart}
                </div>
            ) : null}
        </div>
    )
}
