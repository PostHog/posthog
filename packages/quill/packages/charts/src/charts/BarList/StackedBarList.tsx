import React, { useMemo } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { BarChartConfig, ChartTheme, PointClickData, Series, TooltipContext, ValueDomain } from '../../core/types'
import { BarChart } from '../BarChart/BarChart'

export interface StackedBarListConfig {
    /** `start` (default) puts the label left of the bar and the value right of it. `top` puts the
     *  label and the value on one line above the bar, so the bar and a long label get the full width. */
    labelPosition?: 'start' | 'top'
    /** Row height in px, label line included. Default 28, or 40 with `labelPosition: 'top'`. */
    rowHeight?: number
    /** Bar thickness in px. Default 12, or 8 with `labelPosition: 'top'`. */
    barHeight?: number
    /** Corner radius in px for the bar and its track. Default 4. */
    barCornerRadius?: number
    /** Value-axis domain. Defaults to 0 up to the largest row total. */
    valueDomain?: ValueDomain
    tooltip?: {
        enabled?: boolean
    }
}

export interface StackedBarListProps<Meta = unknown> {
    /** One row per label. Labels must be unique, as on every bar chart. */
    labels: string[]
    /** Stacked segments, as on a stacked `BarChart`: `data[i]` is the segment's value in row `i`.
     *  `trackData[i]` caps the track of row `i`, and the region past it is inert. */
    series: Series<Meta>[]
    theme: ChartTheme
    config?: StackedBarListConfig
    /** Content of the label cell of row `rowIndex`. The cell is a flex row that truncates, so wrap
     *  long text in a `truncate` element. */
    renderLabel: (rowIndex: number) => React.ReactNode
    /** Content of the value cell of row `rowIndex`. */
    renderValue: (rowIndex: number) => React.ReactNode
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const DEFAULT_ROW_HEIGHT = { start: 28, top: 40 }
const DEFAULT_BAR_HEIGHT = { start: 12, top: 8 }
const DEFAULT_CORNER_RADIUS = 4
// Keeps a row with a tiny value visible as a nub next to the largest row.
const MIN_BAR_SIZE = 4
// The `top` label line is `h-4`, and it sits this far above its bar.
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
    theme,
    config,
    renderLabel,
    renderValue,
    tooltip,
    onPointClick,
    dataAttr,
    onError,
}: StackedBarListProps<Meta>): React.ReactElement {
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

    // Each bar is centered in its row, so a `top` label line fits in the space above the bar. When that
    // space is too small for the first row's label, the plot moves down by the difference.
    const barOffsetInRow = (rowHeight - barHeight) / 2
    const plotTop = labelPosition === 'top' ? Math.max(0, TOP_LABEL_LINE_HEIGHT + TOP_LABEL_GAP - barOffsetInRow) : 0

    // The stacked layout makes the bar exactly `barHeight` thick. The grouped layout insets each bar
    // inside its band, and the band padding then no longer maps to a thickness in px.
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
                valueDomain: resolvedValueDomain,
            },
            // `band` so a row reports its tooltip over its track too, not only over its painted bar.
            tooltip: { enabled: tooltipConfig?.enabled !== false, hitArea: 'band' },
        }),
        [barCornerRadius, barHeight, rowHeight, plotTop, resolvedValueDomain, tooltipConfig?.enabled]
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
            />
        ) : null

    if (labelPosition === 'top') {
        // The chart fills the list, and each label line sits on top of it, just above its bar.
        return (
            <div
                className="relative min-w-0 text-xs"
                // eslint-disable-next-line react/forbid-dom-props -- height comes from the row count
                style={{ height: plotTop + labels.length * rowHeight }}
            >
                <div className="absolute inset-0 flex flex-col">{chart}</div>
                {labels.map((label, i) => (
                    <div
                        key={label}
                        className="absolute inset-x-0 flex h-4 items-center justify-between gap-2"
                        // eslint-disable-next-line react/forbid-dom-props -- position comes from the row index
                        style={{
                            top: plotTop + i * rowHeight + barOffsetInRow - TOP_LABEL_GAP - TOP_LABEL_LINE_HEIGHT,
                        }}
                    >
                        <div className="flex min-w-0 items-center gap-1.5">{renderLabel(i)}</div>
                        <div className="shrink-0 whitespace-nowrap text-muted tabular-nums">{renderValue(i)}</div>
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
                gridTemplateRows: `repeat(${labels.length}, ${rowHeight}px)`,
            }}
        >
            {labels.map((label, i) => (
                <React.Fragment key={label}>
                    <div
                        className="flex min-w-0 items-center gap-1.5 col-start-1"
                        // eslint-disable-next-line react/forbid-dom-props -- row position comes from data
                        style={{ gridRow: i + 1 }}
                    >
                        {renderLabel(i)}
                    </div>
                    <div
                        className="col-start-3 whitespace-nowrap text-right text-muted tabular-nums"
                        // eslint-disable-next-line react/forbid-dom-props -- row position comes from data
                        style={{ gridRow: i + 1 }}
                    >
                        {renderValue(i)}
                    </div>
                </React.Fragment>
            ))}
            {chart ? (
                <div
                    className="col-start-2 row-start-1 flex flex-col self-stretch"
                    // eslint-disable-next-line react/forbid-dom-props -- spans every row
                    style={{ gridRowEnd: `span ${labels.length}` }}
                >
                    {chart}
                </div>
            ) : null}
        </div>
    )
}
