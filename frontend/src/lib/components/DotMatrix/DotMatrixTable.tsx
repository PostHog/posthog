import { LemonTable, type LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { DotMatrixCell, type DotMatrixCellProps } from './DotMatrixCell'
import type { DotMatrixAxisItem, DotMatrixData, DotMatrixProps } from './types'

interface DotMatrixTableProps<D extends Record<string, unknown>> extends Pick<
    DotMatrixProps<D>,
    'rowHeader' | 'trailingColumns' | 'rowClassName' | 'loading' | 'emptyState' | 'pageSize'
> {
    matrix: DotMatrixData<D>
    cellWidth: number
    cellOptions: Omit<DotMatrixCellProps<D>, 'cell' | 'row' | 'column'>
}

export function DotMatrixTable<D extends Record<string, unknown>>({
    matrix,
    cellWidth,
    cellOptions,
    rowHeader = { title: 'Row' },
    trailingColumns = [],
    rowClassName,
    loading,
    emptyState,
    pageSize,
}: DotMatrixTableProps<D>): JSX.Element {
    const rowHeaderWidth = rowHeader.width ?? 220
    const tableColumns: LemonTableColumns<DotMatrixAxisItem> = [
        {
            key: 'row',
            title: rowHeader.title,
            width: rowHeaderWidth,
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
            render: (_: unknown, row: DotMatrixAxisItem) => (
                <DotMatrixCell cell={matrix.getCell(row.key, column.key)} row={row} column={column} {...cellOptions} />
            ),
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
        rowHeaderWidth +
        matrix.columns.length * cellWidth +
        trailingColumns.reduce((width, column) => width + column.width, 0)

    return (
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
            pagination={pageSize ? { pageSize } : undefined}
            useURLForSorting={false}
        />
    )
}
