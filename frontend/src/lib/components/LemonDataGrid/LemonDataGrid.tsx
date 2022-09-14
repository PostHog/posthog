import * as React from 'react'
import { LemonTableColumn } from 'lib/components/LemonTable'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { MultiGrid } from 'react-virtualized/dist/es/MultiGrid'
import { GridCellRenderer } from 'react-virtualized/dist/es/Grid'
import { useMemo } from 'react'
import clsx from 'clsx'
import './LemonDataGrid.scss'

interface LemonDataGridProps<T extends Record<string, any>> {
    columns: LemonTableColumn<T, keyof T | undefined>[]
    className?: string
    dataSource: T[]
    fixedColumnCount?: number
    'data-attr'?: string
}

export function LemonDataGrid<T extends Record<string, any>>(props: LemonDataGridProps<T>): JSX.Element {
    const cache = useMemo(
        () =>
            new CellMeasurerCache({
                defaultHeight: 48,
                defaultWidth: 150,
                fixedHeight: true,
            }),
        []
    )

    const cellRenderer: GridCellRenderer = ({ columnIndex, key, parent, rowIndex: _rowIndex, style }) => {
        const rowIndex = _rowIndex - 1
        const column = props.columns[columnIndex]
        // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
        const columnKey = column.key!
        const data = rowIndex >= 0 ? props.dataSource[rowIndex][columnKey] : column.title
        const content = rowIndex >= 0 ? column.render?.(data, props.dataSource[rowIndex], rowIndex) ?? data : data
        return (
            <CellMeasurer cache={cache} columnIndex={columnIndex} key={key} parent={parent} rowIndex={_rowIndex}>
                <div
                    className={clsx({ 'LemonDataGrid--cell': true, 'LemonDataGrid--header': _rowIndex === 0 })}
                    /* eslint-disable-next-line react/forbid-dom-props */
                    style={style}
                >
                    {content}
                </div>
            </CellMeasurer>
        )
    }

    return (
        <AutoSizer disableHeight>
            {({ width }) => (
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width }}
                    data-attr={props['data-attr']}
                    className={clsx('LemonDataGrid', props.className)}
                >
                    <MultiGrid
                        columnCount={props.columns.length}
                        columnWidth={cache.columnWidth}
                        deferredMeasurementCache={cache}
                        fixedColumnCount={props.fixedColumnCount ?? 0}
                        fixedRowCount={1}
                        autoHeight
                        height={(props.dataSource.length + 1) * 48}
                        overscanColumnCount={0}
                        overscanRowCount={0}
                        cellRenderer={cellRenderer}
                        rowCount={props.dataSource.length + 1}
                        rowHeight={48}
                        width={width}
                    />
                </div>
            )}
        </AutoSizer>
    )
}
