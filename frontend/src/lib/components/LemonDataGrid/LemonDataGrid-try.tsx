import * as React from 'react'
import { LemonTableColumn } from 'lib/components/LemonTable'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { Grid, GridCellRenderer } from 'react-virtualized/dist/es/Grid'
// import { OnScrollParams, ScrollSync } from 'react-virtualized/dist/es/ScrollSync'
import { WindowScroller } from 'react-virtualized/dist/es/WindowScroller'
import { useMemo, useState } from 'react'
import clsx from 'clsx'
import './LemonDataGrid.scss'
import { CellMeasurerCacheDecorator } from './CellMeasurerCacheDecorator'

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
const defaultWidth = 50

export function LemonDataGrid<T extends Record<string, any>>(props: LemonDataGridProps<T>): JSX.Element {
    const cache = useMemo(
        () =>
            new CellMeasurerCache({
                defaultHeight: rowHeight,
                defaultWidth,
                fixedHeight: true,
            }),
        []
    )
    const [, setWindowScrollerRef] = useState(null as WindowScroller | null)

    return (
        <WindowScroller ref={(windowScroller) => setWindowScrollerRef(windowScroller)} scrollElement={window}>
            {(windowScrollerProps) => {
                return (
                    <div className="LemonDataGrid--windowscrollwrapper">
                        <AutoSizer disableHeight>
                            {(autoSizerProps) => {
                                return (
                                    <div ref={windowScrollerProps.registerChild}>
                                        <LemonDataGridInternal<T>
                                            {...props}
                                            {...windowScrollerProps}
                                            {...autoSizerProps}
                                            cache={cache}
                                        />
                                    </div>
                                )
                            }}
                        </AutoSizer>
                    </div>
                )
            }}
        </WindowScroller>
    )
}

interface LemonDataGridInternalProps<T extends Record<string, any>> extends LemonDataGridProps<T> {
    cache: CellMeasurerCache
    height: number
    width: number
    isScrolling: boolean
    scrollTop: number
    scrollLeft: number
    onChildScroll: (params: { scrollTop: number }) => void
    registerChild: (element?: React.ReactNode) => void
    // clientHeight: number
    // clientWidth: number
    // scrollHeight: number
    // scrollLeft: number
    // scrollTop: number
    // scrollWidth: number
    // onScroll: (params: OnScrollParams) => void
    // width: number
    // height: number
}

function LemonDataGridInternal<T extends Record<string, any>>(props: LemonDataGridInternalProps<T>): JSX.Element {
    const { width, scrollLeft, cache, columns, dataSource } = props
    console.log(props)
    const headerRenderer: GridCellRenderer = ({ columnIndex, key, parent, style }) => {
        const column = columns[columnIndex]

        return (
            <CellMeasurer cache={cache} columnIndex={columnIndex} key={key} parent={parent} rowIndex={0}>
                <div
                    className={'LemonDataGrid--cell LemonDataGrid--header-cell'}
                    /* eslint-disable-next-line react/forbid-dom-props */
                    style={style}
                >
                    {column.title}
                </div>
            </CellMeasurer>
        )
    }

    const cellRenderer: GridCellRenderer = ({ columnIndex, key, parent, rowIndex, style }) => {
        const column = columns[columnIndex]
        const value = column.key ? dataSource[rowIndex - 1][column.key] : ''
        const content = column.render?.(value, dataSource[rowIndex - 1], rowIndex) ?? value
        return (
            <CellMeasurer cache={cache} columnIndex={columnIndex} key={key} parent={parent} rowIndex={rowIndex}>
                <div
                    className={'LemonDataGrid--cell LemonDataGrid--body-cell'}
                    /* eslint-disable-next-line react/forbid-dom-props */
                    style={style}
                >
                    {content}
                </div>
            </CellMeasurer>
        )
    }

    let fixedColumnCount = props.fixedColumnCount ?? 0
    let fixedWidth = 0
    for (let i = 0; i < fixedColumnCount; i++) {
        fixedWidth += cache.columnWidth({ index: i }) || defaultWidth
    }
    if (width < fixedWidth + defaultWidth * 2) {
        fixedColumnCount = 0
        fixedWidth = 0
    }

    const common = {
        rowHeight,
        overscanColumnCount: 5,
        overscanRowCount: 5,
        estimatedColumnSize: defaultWidth,
    }

    const cacheTopRight: CellMeasurerCache = useMemo(
        () =>
            fixedColumnCount > 0
                ? new CellMeasurerCacheDecorator({
                      cellMeasurerCache: cache,
                      columnIndexOffset: fixedColumnCount,
                      rowIndexOffset: 0,
                  })
                : cache,
        [cache, fixedColumnCount]
    )

    const cacheBottomLeft: CellMeasurerCache = useMemo(
        () =>
            fixedColumnCount > 0
                ? new CellMeasurerCacheDecorator({
                      cellMeasurerCache: cache,
                      columnIndexOffset: 0,
                      rowIndexOffset: 1,
                  })
                : cache,
        [cache, fixedColumnCount]
    )

    const cacheBottomRight: CellMeasurerCache = useMemo(
        () =>
            fixedColumnCount > 0
                ? new CellMeasurerCacheDecorator({
                      cellMeasurerCache: cache,
                      columnIndexOffset: fixedColumnCount,
                      rowIndexOffset: 1,
                  })
                : cache,
        [cache, fixedColumnCount]
    )

    return (
        <div className="LemonDataGrid">
            <div className="relative w-full" style={{ height: rowHeight }}>
                {fixedColumnCount > 0 ? (
                    <Grid
                        {...common}
                        deferredMeasurementCache={cache}
                        columnWidth={cache.columnWidth}
                        cellRenderer={headerRenderer}
                        rowCount={1}
                        columnCount={fixedColumnCount}
                        width={fixedWidth}
                        height={rowHeight}
                        style={{ overflow: 'hidden', position: 'absolute', left: 0, top: 0 }}
                    />
                ) : null}
                <Grid
                    {...common}
                    deferredMeasurementCache={cacheTopRight}
                    columnWidth={cacheTopRight.columnWidth}
                    cellRenderer={(props) =>
                        headerRenderer({
                            ...props,
                            columnIndex: props.columnIndex + fixedColumnCount,
                        })
                    }
                    rowCount={1}
                    columnCount={columns.length - fixedColumnCount}
                    scrollLeft={scrollLeft}
                    width={width - fixedWidth}
                    height={rowHeight}
                    className="LemonDataGrid--very-hidden"
                    style={{ position: 'absolute', left: fixedWidth, top: 0 }}
                    containerStyle={{ overflow: 'hidden' }}
                />
            </div>

            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width, ...props.style }}
                data-attr={props['data-attr']}
                className={clsx('', 'relative', props.className)}
            >
                {fixedColumnCount > 0 ? (
                    <Grid
                        {...common}
                        deferredMeasurementCache={cacheBottomLeft}
                        columnWidth={cacheBottomLeft.columnWidth}
                        cellRenderer={(props) =>
                            cellRenderer({
                                ...props,
                                rowIndex: props.rowIndex + 1,
                            })
                        }
                        rowCount={dataSource.length}
                        columnCount={fixedColumnCount || columns.length}
                        width={fixedWidth}
                        height={dataSource.length * rowHeight}
                        style={{ position: 'absolute', left: 0 }}
                    />
                ) : null}

                <Grid
                    {...common}
                    deferredMeasurementCache={cacheBottomRight}
                    columnWidth={cacheBottomRight.columnWidth}
                    cellRenderer={(props) =>
                        cellRenderer({
                            ...props,
                            columnIndex: props.columnIndex + fixedColumnCount,
                            rowIndex: props.rowIndex + 1,
                        })
                    }
                    autoHeight
                    // onScroll={onScroll}
                    rowCount={dataSource.length}
                    columnCount={columns.length - fixedColumnCount}
                    width={width - fixedWidth}
                    height={dataSource.length * rowHeight + 15}
                    style={{ position: 'relative', marginLeft: fixedWidth }}
                />
            </div>
        </div>
    )
}
