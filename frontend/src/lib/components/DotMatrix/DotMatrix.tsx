import './DotMatrix.scss'

import clsx from 'clsx'
import { useMemo } from 'react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { CountCell } from './CountCell'
import { DotGlyph } from './DotGlyph'
import { getDotMatrixCellCount, normalizeDotMatrixData } from './dotMatrixData'
import { DotMatrixLegend } from './DotMatrixLegend'
import { DotMatrixTooltip } from './DotMatrixTooltip'
import type { DotMatrixAxisItem, DotMatrixProps } from './types'

export function DotMatrix<D extends Record<string, unknown>>({
    data,
    fields,
    rows,
    columns,
    series,
    groups = [],
    mode = fields.series !== undefined ? 'dots' : 'count',
    sizeThresholds = [1, 5, 10],
    countScale,
    countOf = fields.series !== undefined ? 'activeSeries' : 'value',
    selectedSeries = [],
    onSelectedSeriesChange,
    aggregateSelection,
    rowHeader = { title: 'Row' },
    trailingColumns = [],
    renderCell,
    renderTooltip,
    onCellClick,
    cellWidth = mode === 'dots' ? 110 : 64,
    rowClassName,
    className,
    legend,
    loading = false,
    emptyState = 'No data to display. Add data to see the matrix.',
}: DotMatrixProps<D>): JSX.Element {
    const matrix = useMemo(
        () => normalizeDotMatrixData({ data, fields, rows, columns, series }),
        [data, fields, rows, columns, series]
    )
    const coloredSeries = useMemo(
        () =>
            matrix.series.map((item, index) => ({
                ...item,
                color:
                    item.color ??
                    groups.find((group) => group.key === item.group)?.color ??
                    `var(--data-color-${(index % 15) + 1})`,
            })),
        [matrix.series, groups]
    )

    const renderMatrixCell = (row: DotMatrixAxisItem, columnKey: string): JSX.Element => {
        const cell = matrix.getCell(row.key, columnKey)
        const column = matrix.columns.find((item) => item.key === columnKey)
        const label = `${row.label ?? row.key}, ${column?.label ?? columnKey}`
        const count =
            mode === 'count' ? getDotMatrixCellCount(cell, { countOf, selectedSeries, aggregateSelection }) : null
        const cellDescription =
            mode === 'dots'
                ? coloredSeries
                      .filter((item) => cell.values[item.key] > 0)
                      .map((item) => `${item.label ?? item.key}: ${cell.values[item.key]}`)
                      .join(', ') || 'No activity'
                : count === null
                  ? 'Combined count unavailable'
                  : String(count)
        const content = renderCell ? (
            renderCell(cell)
        ) : mode === 'dots' ? (
            <DotGlyph
                series={coloredSeries}
                groups={groups}
                values={cell.values}
                sizeThresholds={sizeThresholds}
                label={label}
            />
        ) : (
            <CountCell value={count} scale={countScale} label={label} />
        )
        const cellContent = onCellClick ? (
            <button
                type="button"
                className="DotMatrix__cell DotMatrix__cell--interactive"
                data-attr="dot-matrix-cell"
                onClick={() => onCellClick(cell)}
                aria-label={`${label}: ${cellDescription}`}
            >
                {content}
            </button>
        ) : (
            <div className="DotMatrix__cell" tabIndex={renderCell ? undefined : 0}>
                {content}
            </div>
        )
        return (
            <Tooltip
                title={
                    renderTooltip ? (
                        renderTooltip(cell)
                    ) : (
                        <DotMatrixTooltip
                            cell={cell}
                            rowLabel={row.label ?? row.key}
                            columnLabel={column?.label ?? columnKey}
                            series={coloredSeries}
                        />
                    )
                }
                delayMs={100}
                placement="bottom"
                className="DotMatrix__tooltip"
            >
                {cellContent}
            </Tooltip>
        )
    }

    const tableColumns: LemonTableColumns<DotMatrixAxisItem> = [
        {
            key: 'row',
            title: rowHeader.title,
            width: rowHeader.width ?? 220,
            className: 'DotMatrix__row-header',
            render: (_, row) =>
                rowHeader.render ? (
                    rowHeader.render(row)
                ) : (
                    <span className="DotMatrix__row-label">{row.label ?? row.key}</span>
                ),
        },
        ...matrix.columns.map((column) => ({
            key: `column:${column.key}`,
            width: cellWidth,
            className: 'DotMatrix__bucket',
            title: (
                <div className="DotMatrix__column-label">
                    <span>{column.label ?? column.key}</span>
                    {column.partial && <span className="DotMatrix__partial">To date</span>}
                </div>
            ),
            render: (_: unknown, row: DotMatrixAxisItem) => renderMatrixCell(row, column.key),
        })),
        ...trailingColumns.map((column) => ({
            key: `trailing:${column.key}`,
            title: column.title,
            width: column.width,
            className: 'DotMatrix__trailing',
            render: (_: unknown, row: DotMatrixAxisItem) => column.render(row.key),
        })),
        {
            key: 'filler',
            className: 'DotMatrix__filler',
            render: () => ({ children: null, props: { 'aria-hidden': true } }),
        },
    ]

    const tableWidth =
        (rowHeader.width ?? 220) +
        matrix.columns.length * cellWidth +
        trailingColumns.reduce((width, column) => width + column.width, 0)

    return (
        <div className={clsx('DotMatrix', `DotMatrix--${mode}`, className)}>
            {legend !== false && coloredSeries.length > 0 && (
                <DotMatrixLegend
                    series={coloredSeries}
                    groups={groups}
                    mode={mode}
                    sizeThresholds={sizeThresholds}
                    countScale={countScale}
                    selectedSeries={selectedSeries}
                    onSelectedSeriesChange={onSelectedSeriesChange}
                    labels={legend}
                />
            )}
            <LemonTable<DotMatrixAxisItem>
                className="DotMatrix__table"
                data-attr="dot-matrix-table"
                columns={tableColumns}
                dataSource={matrix.rows}
                rowKey="key"
                rowClassName={rowClassName}
                firstColumnSticky
                tableLayout="fixed"
                tableStyle={{ width: '100%', minWidth: tableWidth }}
                loading={loading}
                emptyState={emptyState}
                useURLForSorting={false}
            />
        </div>
    )
}
