import React, { useCallback, useMemo } from 'react'

import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type {
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    Series,
} from '../../core/types'
import {
    cellRect,
    computeHeatmapLayout,
    heatmapCellColor,
    maxCellValue,
    normalizeCount,
    rowAtY,
    type HeatmapColorScale,
    type HeatmapLayout,
} from './heatmap-layout'
import { HeatmapTooltip, type HeatmapRowMeta, type HeatmapTooltipContext } from './HeatmapTooltip'

/** Stash slot — survives a render via `ChartScales._private` so drawStatic/drawHover/
 *  wrapClickData can read the grid layout without recomputing it. */
interface HeatmapPrivate {
    __heatmap: {
        layout: HeatmapLayout
        cells: number[][]
        accent: string
        maxValue: number
        colorScale: HeatmapColorScale
    }
}

export interface HeatmapConfig {
    /** Custom x-axis tick label formatter. Return null to skip a tick. Called with (label, index). */
    xTickFormatter?: (label: string, index: number) => string | null
    /** How counts map to color intensity. Defaults to 'log' — right for long-tailed count grids. */
    colorScale?: HeatmapColorScale
    /** Accent color for the density ramp (hex, rgb, or var(--…)). Defaults to the first theme
     *  palette color. */
    color?: string
    xAxisLabel?: string
    yAxisLabel?: string
    hideXAxis?: boolean
    hideYAxis?: boolean
    /** Per-side margin overrides. Should be referentially stable. */
    margins?: Partial<ChartMargins>
    tooltip?: {
        /** Show the single-cell tooltip on hover. Defaults to true. */
        enabled?: boolean
        /** Formats the column (x) label in the tooltip header. */
        labelFormatter?: (label: string) => React.ReactNode
        /** Formats the cell count. Defaults to `toLocaleString`. */
        valueFormatter?: (value: number) => React.ReactNode
    }
}

export interface HeatmapCellDatum {
    /** Column index into `xLabels`. */
    xIndex: number
    /** Row index into `yLabels` (0 = bottom row). */
    yIndex: number
    xLabel: string
    yLabel: string
    /** The cell's count. */
    value: number
}

export interface HeatmapProps {
    /** Column labels, left to right. */
    xLabels: string[]
    /** Row labels, bottom to top — `yLabels[0]` is the bottom row (smallest bucket). */
    yLabels: string[]
    /** Dense grid of counts: `cells[rowIndex][colIndex]`, aligned with `yLabels`/`xLabels`.
     *  0 (or a missing entry) means an empty cell — nothing is drawn there. */
    cells: number[][]
    theme: ChartTheme
    config?: HeatmapConfig
    /** Custom tooltip. Each `ctx.seriesData` entry is one row at the hovered column; narrow to
     *  the hovered cell via `findClosestSeriesKey(ctx.seriesData, ctx.hoverPosition.y)`. */
    tooltip?: (ctx: HeatmapTooltipContext) => React.ReactNode
    /** Fired when the user clicks a cell. */
    onCellClick?: (cell: HeatmapCellDatum) => void
    className?: string
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function Heatmap({ onError, ...rest }: HeatmapProps): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <HeatmapInner {...rest} />
        </ChartErrorBoundary>
    )
}

function HeatmapInner({
    xLabels,
    yLabels,
    cells,
    theme,
    config,
    tooltip,
    onCellClick,
    className,
    dataAttr,
    children,
}: Omit<HeatmapProps, 'onError'>): React.ReactElement {
    const { colorScale = 'log' } = config ?? {}
    const accent = config?.color || theme.colors[0] || '#1d4aff'

    // Dense row-major grid padded to the label counts, so a ragged `cells` input can't
    // desync the draw loop from the axis.
    const grid = useMemo<number[][]>(
        () => yLabels.map((_, r) => xLabels.map((_, c) => cells[r]?.[c] ?? 0)),
        [yLabels, xLabels, cells]
    )
    const maxValue = useMemo(() => maxCellValue(grid), [grid])

    // One adapter series per row: `data` is that row's counts (tooltip values), `meta.rowIndex`
    // maps back to the grid. All rows share the accent so tooltip swatches stay consistent.
    const adaptedSeries = useMemo<Series<HeatmapRowMeta>[]>(
        () =>
            yLabels.map((yLabel, rowIndex) => ({
                key: `row:${rowIndex}`,
                label: yLabel,
                data: grid[rowIndex],
                color: accent,
                meta: { rowIndex },
            })),
        [yLabels, grid, accent]
    )

    // The y "value" space is row units: rowIndex → bottom edge, rowIndex + 1 → top edge,
    // rowIndex + 0.5 → center. Ticks sit at row centers and format to the row's label.
    const yTickFormatter = useCallback(
        (value: number): string => {
            if (yLabels.length === 0) {
                return ''
            }
            const index = Math.min(yLabels.length - 1, Math.max(0, Math.round(value - 0.5)))
            return yLabels[index] ?? ''
        },
        [yLabels]
    )

    // Feeds `useChartMargins` tick sizing: row-center values run through `yTickFormatter`, so
    // the y gutter is measured against the real row labels instead of the cell counts.
    const valueRangeSeries = useMemo<Series[]>(
        () => [{ key: '__heatmap-rows', label: '', data: yLabels.map((_, i) => i + 0.5) }],
        [yLabels]
    )

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            const layout = computeHeatmapLayout(dimensions, scaleLabels.length, yLabels.length)
            const labelIndex = new Map(scaleLabels.map((label, i) => [label, i]))
            const priv: HeatmapPrivate = {
                __heatmap: { layout, cells: grid, accent, maxValue, colorScale },
            }
            return {
                x: (label: string) => {
                    const index = labelIndex.get(label)
                    return index == null ? undefined : layout.plotLeft + (index + 0.5) * layout.colWidth
                },
                y: (value: number) => layout.plotTop + layout.plotHeight - value * layout.rowHeight,
                yTicks: () => yLabels.map((_, i) => i + 0.5),
                extent: () => layout.colWidth,
                _private: priv,
            }
        },
        [yLabels, grid, accent, maxValue, colorScale]
    )

    const drawStatic = useCallback(({ ctx, scales }: ChartDrawArgs) => {
        const priv = (scales._private as HeatmapPrivate | undefined)?.__heatmap
        if (!priv) {
            return
        }
        const { layout, cells: drawCells, accent: drawAccent, maxValue: max, colorScale: scale } = priv
        // A 1px gutter keeps cells readable as discrete buckets; collapse it when cells are so
        // small the gap would dominate the fill.
        const gap = layout.colWidth > 3 && layout.rowHeight > 3 ? 1 : 0
        for (let r = 0; r < layout.rows; r++) {
            const row = drawCells[r]
            if (!row) {
                continue
            }
            for (let c = 0; c < layout.cols; c++) {
                const value = row[c]
                if (!(value > 0)) {
                    continue
                }
                const rect = cellRect(layout, c, r)
                ctx.fillStyle = heatmapCellColor(drawAccent, normalizeCount(value, max, scale))
                ctx.fillRect(rect.x + gap / 2, rect.y + gap / 2, rect.width - gap, rect.height - gap)
            }
        }
    }, [])

    const drawHover = useCallback(({ ctx, scales, hoverIndex, hoverPosition, hoverProgress }: ChartDrawArgs): boolean => {
        const priv = (scales._private as HeatmapPrivate | undefined)?.__heatmap
        if (!priv || hoverIndex < 0 || !hoverPosition) {
            return false
        }
        const row = rowAtY(priv.layout, hoverPosition.y)
        if (row < 0) {
            return false
        }
        const rect = cellRect(priv.layout, hoverIndex, row)
        ctx.save()
        ctx.globalAlpha = hoverProgress
        ctx.strokeStyle = priv.accent
        ctx.lineWidth = 1.5
        ctx.strokeRect(rect.x + 0.75, rect.y + 0.75, rect.width - 1.5, rect.height - 1.5)
        ctx.restore()
        return true
    }, [])

    // Each row's tooltip anchor spans its cell exactly (top edge → bottom edge), so
    // `findClosestSeriesKey`'s containment pass resolves the hovered cell.
    const resolvePositionValue: ResolveValueFn = useCallback(
        (series) => ((series.meta as HeatmapRowMeta | undefined)?.rowIndex ?? 0) + 1,
        []
    )
    const resolveBottomValue: ResolveValueFn = useCallback(
        (series) => (series.meta as HeatmapRowMeta | undefined)?.rowIndex ?? 0,
        []
    )

    // Rewrite clicks to the row under the cursor — the base chart's click payload carries the
    // first series at the column, which is meaningless for a grid.
    const wrapClickData = useCallback(
        (data: PointClickData<HeatmapRowMeta>, scales: ChartScales): PointClickData<HeatmapRowMeta> => {
            const priv = (scales._private as HeatmapPrivate | undefined)?.__heatmap
            if (!priv || !data.cursor) {
                return data
            }
            const row = rowAtY(priv.layout, data.cursor.y)
            const match = data.crossSeriesData.find((entry) => entry.series.meta?.rowIndex === row)
            if (row < 0 || !match) {
                return data
            }
            return { ...data, series: match.series, seriesIndex: row, value: match.value }
        },
        []
    )

    const handlePointClick = useCallback(
        (data: PointClickData<HeatmapRowMeta>): void => {
            const rowIndex = data.series.meta?.rowIndex
            if (rowIndex == null || !onCellClick) {
                return
            }
            onCellClick({
                xIndex: data.dataIndex,
                yIndex: rowIndex,
                xLabel: data.label,
                yLabel: yLabels[rowIndex] ?? '',
                value: data.value,
            })
        },
        [onCellClick, yLabels]
    )

    const tooltipLabelFormatter = config?.tooltip?.labelFormatter
    const tooltipValueFormatter = config?.tooltip?.valueFormatter
    const renderTooltip = useMemo(
        () =>
            tooltip ??
            ((ctx: HeatmapTooltipContext) => (
                <HeatmapTooltip ctx={ctx} labelFormatter={tooltipLabelFormatter} valueFormatter={tooltipValueFormatter} />
            )),
        [tooltip, tooltipLabelFormatter, tooltipValueFormatter]
    )

    const baseConfig = useMemo<ChartConfig>(
        () => ({
            xTickFormatter: config?.xTickFormatter,
            yTickFormatter,
            xAxisLabel: config?.xAxisLabel,
            yAxisLabel: config?.yAxisLabel,
            hideXAxis: config?.hideXAxis,
            hideYAxis: config?.hideYAxis,
            margins: config?.margins,
            // 'cursor' placement: a follow-data anchor would pin the tooltip to the column top,
            // far from the hovered cell in a tall grid.
            tooltip: { enabled: config?.tooltip?.enabled, placement: 'cursor' },
        }),
        [
            config?.xTickFormatter,
            yTickFormatter,
            config?.xAxisLabel,
            config?.yAxisLabel,
            config?.hideXAxis,
            config?.hideYAxis,
            config?.margins,
            config?.tooltip?.enabled,
        ]
    )

    return (
        <Chart<HeatmapRowMeta>
            series={adaptedSeries}
            labels={xLabels}
            config={baseConfig}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={renderTooltip}
            onPointClick={onCellClick ? handlePointClick : undefined}
            wrapClickData={wrapClickData}
            resolvePositionValue={resolvePositionValue}
            resolveBottomValue={resolveBottomValue}
            valueRangeSeries={valueRangeSeries}
            className={className}
            dataAttr={dataAttr}
        >
            {children}
        </Chart>
    )
}
