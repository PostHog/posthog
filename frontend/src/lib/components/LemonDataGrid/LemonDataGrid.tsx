import * as React from 'react'
import { LemonTableColumn } from 'lib/components/LemonTable'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { MultiGrid } from './MultiGrid'
import { GridCellRenderer } from 'react-virtualized/dist/es/Grid'
import { ReactNode, useEffect, useMemo, useRef } from 'react'
import clsx from 'clsx'
import './LemonDataGrid.scss'

interface LemonDataGridProps<T extends Record<string, any>> {
    columns: LemonTableColumn<T, keyof T | undefined>[]
    className?: string
    style?: React.CSSProperties
    dataSource: T[]
    fixedColumnCount?: number
    'data-attr'?: string
}

/** Defaults for calculation if nothing overrides */
const rowHeight = 48
const defaultWidth = 100

export function LemonDataGrid<T extends Record<string, any>>(props: LemonDataGridProps<T>): JSX.Element {
    const cache = useMemo(
        () =>
            new CellMeasurerCache({
                defaultHeight: rowHeight,
                defaultWidth,
                // fixedHeight: true,
            }),
        []
    )
    const multiGridRef = useRef<MultiGrid | null>(null)
    useEffect(() => {
        multiGridRef.current?.forceUpdateGrids()
    }, [props.dataSource, props.columns])

    const cellRenderer: GridCellRenderer = ({ columnIndex, key, parent, rowIndex, style }) => {
        let content: string | ReactNode
        if (columnIndex === props.columns.length) {
            // filter column after the table
        } else if (rowIndex === 0) {
            content = props.columns[columnIndex]?.title || ''
        } else {
            const column = props.columns[columnIndex]
            const value = props.dataSource[rowIndex - 1][column.key ?? '']
            content = column.render?.(value, props.dataSource[rowIndex - 1], rowIndex - 1) ?? value
        }
        const className = clsx({
            'LemonDataGrid--cell': true,
            'LemonDataGrid--header': rowIndex === 0,
            [`justify-start`]: props.columns[columnIndex]?.align === 'left',
            [`justify-center`]: props.columns[columnIndex]?.align === 'center',
            [`justify-end`]: props.columns[columnIndex]?.align === 'right',
        })

        return (
            <CellMeasurer cache={cache} columnIndex={columnIndex} key={key} parent={parent} rowIndex={rowIndex}>
                {columnIndex === props.columns.length ? (
                    <div
                        className={className}
                        /* eslint-disable-next-line react/forbid-dom-props */
                        style={style}
                    />
                ) : (
                    <div
                        className={className}
                        /* eslint-disable-next-line react/forbid-dom-props */
                        style={style}
                    >
                        {content}
                    </div>
                )}
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
                        ref={(ref) => {
                            multiGridRef.current = ref
                        }}
                        columnCount={props.columns.length}
                        columnWidth={cache.columnWidth}
                        deferredMeasurementCache={cache}
                        fixedColumnCount={props.fixedColumnCount ?? 0}
                        fixedRowCount={1}
                        overscanColumnCount={0}
                        overscanRowCount={0}
                        cellRenderer={cellRenderer}
                        rowCount={props.dataSource.length + 1}
                        rowHeight={rowHeight}
                        width={width}
                        height={0} /** not used */
                    />
                </div>
            )}
        </AutoSizer>
    )
}
