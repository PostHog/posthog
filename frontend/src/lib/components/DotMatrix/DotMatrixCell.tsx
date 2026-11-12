import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { CountCell } from './CountCell'
import { DotGlyph } from './DotGlyph'
import { getDotMatrixCellCount } from './dotMatrixData'
import { getDotMatrixActiveSeries } from './dotMatrixPresentation'
import { DotMatrixTooltip } from './DotMatrixTooltip'
import type {
    DotMatrixAxisItem,
    DotMatrixCell as Cell,
    DotMatrixColumn,
    DotMatrixProps,
    DotMatrixSeries,
} from './types'

export interface DotMatrixCellProps<D extends Record<string, unknown>> extends Pick<
    DotMatrixProps<D>,
    | 'groups'
    | 'columnsPerGroup'
    | 'firstUseSeries'
    | 'sizeThresholds'
    | 'countScale'
    | 'countOf'
    | 'selectedSeries'
    | 'aggregateSelection'
    | 'renderCell'
    | 'renderTooltip'
    | 'tooltipInteractive'
    | 'onCellClick'
> {
    cell: Cell<D>
    row: DotMatrixAxisItem
    column: DotMatrixColumn
    mode: 'dots' | 'count'
    series: DotMatrixSeries[]
    hoveredSeries?: string | null
}

export function DotMatrixCell<D extends Record<string, unknown>>({
    cell,
    row,
    column,
    mode,
    series,
    groups,
    columnsPerGroup,
    firstUseSeries,
    sizeThresholds,
    countScale,
    countOf,
    selectedSeries,
    aggregateSelection,
    renderCell,
    renderTooltip,
    tooltipInteractive,
    hoveredSeries,
    onCellClick,
}: DotMatrixCellProps<D>): JSX.Element {
    const label = `${row.label ?? row.key}, ${column.label ?? column.key}`
    const count = mode === 'count' ? getDotMatrixCellCount(cell, { countOf, selectedSeries, aggregateSelection }) : null
    const cellDescription =
        mode === 'dots'
            ? getDotMatrixActiveSeries(series, cell.values)
                  .map((item) => `${item.label ?? item.key}: ${cell.values[item.key]}`)
                  .join(', ') || 'No activity'
            : count === null
              ? 'Combined count unavailable'
              : String(count)
    const content = renderCell ? (
        renderCell(cell)
    ) : mode === 'dots' ? (
        <DotGlyph
            series={series}
            groups={groups}
            columnsPerGroup={columnsPerGroup}
            firstUseSeries={firstUseSeries?.(cell)}
            values={cell.values}
            hoveredSeries={hoveredSeries}
            sizeThresholds={sizeThresholds}
            label={label}
        />
    ) : (
        <CountCell value={count} scale={countScale} label={label} />
    )
    const tooltipContent = renderTooltip ? (
        renderTooltip(cell)
    ) : (
        <DotMatrixTooltip
            cell={cell}
            rowLabel={row.label ?? row.key}
            columnLabel={column.label ?? column.key}
            series={series}
        />
    )
    const cellContent = onCellClick ? (
        <button
            type="button"
            className="DotMatrix__cell DotMatrix__cell--interactive"
            data-attr="dot-matrix-cell"
            data-row-key={cell.rowKey}
            data-column-key={cell.columnKey}
            onClick={() => onCellClick(cell)}
            aria-label={`${label}: ${cellDescription}`}
        >
            {content}
        </button>
    ) : (
        <div
            className="DotMatrix__cell"
            data-row-key={cell.rowKey}
            data-column-key={cell.columnKey}
            tabIndex={tooltipContent ? 0 : undefined}
        >
            {content}
        </div>
    )
    if (!tooltipContent) {
        return cellContent
    }
    return (
        <Tooltip
            interactive={tooltipInteractive}
            title={tooltipContent}
            delayMs={100}
            placement="bottom"
            className="DotMatrix__tooltip"
        >
            {cellContent}
        </Tooltip>
    )
}
