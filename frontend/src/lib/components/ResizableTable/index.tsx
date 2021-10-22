import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Table, TableProps } from 'antd'
import { ColumnType } from 'antd/lib/table'
import { ResizableProps } from 'react-resizable'
import ResizeObserver from 'resize-observer-polyfill'
import { RenderedCell } from 'rc-table/lib/interface'
import { getFullwidthColumnSize, getMinColumnWidth, parsePixelValue } from 'lib/utils/responsiveUtils'
import VirtualTableHeader from './VirtualTableHeader'
import { TableConfig as _TableConfig } from './TableConfig'
import { useBreakpoint } from 'lib/hooks/useBreakpoint'

import './index.scss'

export const TableConfig = _TableConfig

export interface ResizableColumnType<RecordType> extends ColumnType<RecordType> {
    title: string | JSX.Element
    key?: string
    dataIndex?: string
    render?:
        | ((record: RecordType, ...rest: any) => JSX.Element | string | RenderedCell<RecordType> | null)
        | ((value: any, record?: RecordType, ...rest: any) => JSX.Element | string | RenderedCell<RecordType> | null)
    ellipsis?: boolean
    span: number
    defaultWidth?: number
    eventProperties?: string[]
    widthConstraints?: [number, number] // Override default min and max width (px). To specify no max, use Infinity.
}

export interface InternalColumnType<RecordType> extends ResizableColumnType<RecordType> {
    width?: number
}

export type ResizeHandler = Exclude<ResizableProps['onResize'], undefined>

// https://github.com/ant-design/ant-design/blob/4cdd24f4ec1ffb638175bb6c2dbb4fd7f103d60f/components/table/style/index.less#L422-L424
export const ANTD_EXPAND_BUTTON_WIDTH = 48

interface ResizableTableProps<RecordType> extends TableProps<RecordType> {
    columns: ResizableColumnType<RecordType>[]
}

// Type matches antd.Table
export function ResizableTable<RecordType extends Record<any, any> = any>({
    columns: initialColumns = [],
    components,
    ...props
}: ResizableTableProps<RecordType>): JSX.Element {
    const breakpoint = useBreakpoint()
    const minColumnWidth = getMinColumnWidth(breakpoint)
    const [columns, setColumns] = useState(() => {
        const lastIndex = initialColumns.length
        return initialColumns.map((col, index) => ({
            ...col,
            width: index === lastIndex ? undefined : minColumnWidth,
        })) as InternalColumnType<RecordType>[]
    })
    const [headerColumns, setHeaderColumns] = useState(columns)
    const [headerShouldRender, setHeaderShouldRender] = useState(false)
    const scrollWrapperRef = useRef<HTMLDivElement>(null)
    const overlayRef = useRef<HTMLDivElement>(null)
    const timeout: any = useRef()

    function setScrollableRight(value: boolean): void {
        if (value) {
            return overlayRef?.current?.classList.add('scrollable-right')
        }
        return overlayRef?.current?.classList.remove('scrollable-right')
    }

    function updateScrollGradient(): void {
        if (overlayRef.current) {
            const overlay = overlayRef.current
            if (overlay.offsetWidth + overlay.scrollLeft < overlay.scrollWidth) {
                setScrollableRight(true)
            } else {
                setScrollableRight(false)
            }
        }
    }

    function getColumnCSSWidths(): Array<number | undefined> {
        const columnNodes = scrollWrapperRef.current?.querySelectorAll<HTMLElement>('.ant-table-content colgroup col')
        if (columnNodes) {
            const cols = Array.from(columnNodes)
            return cols.map((col) => (col.style.width ? parsePixelValue(col.style.width) : undefined))
        }
        return []
    }

    function updateColumnWidth(index: number, width: number): void {
        const col = scrollWrapperRef.current?.querySelector(
            // nth-child is 1-indexed. first column is fixed. last column width must be uncontrolled.
            `.ant-table-content colgroup col:nth-child(${index + 1 + Number(!!props.expandable)}):not(:last-child)`
        )
        col?.setAttribute('style', `width: ${width}px;`)
    }

    function unsetLastColumnStyle(): void {
        // last column width must be uncontrolled.
        const col = scrollWrapperRef.current?.querySelector('.ant-table-content colgroup col:last-child')
        col?.removeAttribute('style')
    }

    function updateTableWidth(): void {
        // <table> elements have super strange auto-sizing: (https://css-tricks.com/fixing-tables-long-strings/)
        // We control the width of the <table> based on the width of the virtual header.
        const header = scrollWrapperRef.current?.querySelector('.resizable-virtual-table-header')
        if (header?.childNodes) {
            const children = Array.from(header?.childNodes) as HTMLElement[]
            const headerWidth = children.reduce((total, { offsetWidth }) => total + (offsetWidth ?? 0), 0)
            if (headerWidth) {
                const table = scrollWrapperRef.current?.querySelector('.ant-table table')
                table?.setAttribute('style', `width: ${headerWidth}px;`)
            }
        }
        unsetLastColumnStyle()
    }

    const handleColumnResize =
        (index: number): ResizeHandler =>
        (_, { size: { width } }) => {
            if (timeout.current) {
                cancelAnimationFrame(timeout.current)
            }
            timeout.current = requestAnimationFrame(function () {
                updateColumnWidth(index, width)
                updateTableWidth()
            })
            updateScrollGradient()
        }

    function handleWrapperResize(newWidth: number): void {
        // Recalculate column widths if the wrapper changes size.
        const table = scrollWrapperRef.current?.querySelector('.ant-table table')
        const oldWidth = table?.clientWidth
        if (!oldWidth || oldWidth === newWidth) {
            return
        }
        if (timeout.current) {
            cancelAnimationFrame(timeout.current)
        }
        const resizeRatio = newWidth / oldWidth
        const columnWidths = getColumnCSSWidths()
        timeout.current = requestAnimationFrame(function () {
            setHeaderShouldRender(false)
            setHeaderColumns((cols) => {
                const lastIndex = initialColumns.length - 1
                const nextColumns = cols.map((column, index) =>
                    index === lastIndex
                        ? column
                        : {
                              ...column,
                              width: Math.max(
                                  (columnWidths[index + Number(!!props.expandable)] ?? 0) * resizeRatio,
                                  minColumnWidth
                              ),
                          }
                )
                nextColumns.slice(0, lastIndex).forEach((col, index) => {
                    updateColumnWidth(index, col.width ?? minColumnWidth)
                })
                updateTableWidth()
                return nextColumns
            })
            setHeaderShouldRender(true)
        })
    }

    const resizeObserver = new ResizeObserver((entries: ResizeObserverEntry[]) => {
        entries.forEach(({ contentRect: { width } }) => handleWrapperResize(width))
    })

    useEffect(() => {
        // Update render prop when parent columns change
        setColumns((cols) => {
            const lastIndex = cols.length
            return cols.map((column, index) =>
                index === lastIndex
                    ? column
                    : {
                          ...column,
                          render: initialColumns[index].render,
                      }
            )
        })
    }, [initialColumns])

    useLayoutEffect(
        () => {
            // Calculate relative column widths (px) once the wrapper is mounted.
            if (scrollWrapperRef.current) {
                resizeObserver.observe(scrollWrapperRef.current)
                const wrapperWidth = scrollWrapperRef.current.clientWidth
                const gridBasis = columns.reduce((total, { span }) => total + span, 0)
                const columnSpanWidth = getFullwidthColumnSize(wrapperWidth, gridBasis)
                setColumns((cols) => {
                    const lastIndex = cols.length
                    const nextColumns = cols.map((column, index) =>
                        index === lastIndex
                            ? column
                            : {
                                  ...column,
                                  width: Math.max(column.defaultWidth || columnSpanWidth * column.span, minColumnWidth),
                              }
                    )
                    setHeaderColumns(nextColumns)
                    return nextColumns
                })
                updateScrollGradient()
                setHeaderShouldRender(true)
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    )

    return (
        <div ref={scrollWrapperRef} className="resizable-table-scroll-container" onScroll={updateScrollGradient}>
            <div ref={overlayRef} className="table-gradient-overlay">
                {headerShouldRender && (
                    <VirtualTableHeader
                        columns={headerColumns}
                        handleResize={handleColumnResize}
                        layoutEffect={updateTableWidth}
                        minColumnWidth={minColumnWidth}
                        expandable={props.expandable}
                    />
                )}
                <Table
                    columns={columns}
                    components={{
                        ...components,
                        header: { cell: () => null }, // Nix that header row
                    }}
                    tableLayout="fixed"
                    {...props}
                />
            </div>
        </div>
    )
}
