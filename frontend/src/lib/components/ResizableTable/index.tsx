import React, { useLayoutEffect, useRef, useState } from 'react'
import { Table, TableProps } from 'antd'
import { ResizableProps } from 'react-resizable'
import { getActiveBreakpoint, getFullwidthColumnSize, getMinColumnWidth } from './responsiveUtils'

import './index.scss'
import { ColumnType } from 'antd/lib/table'
import VirtualTableHeader from './VirtualTableHeader'

export interface ResizableColumnType<RecordType> extends ColumnType<RecordType> {
    title: string | JSX.Element
    key?: string
    render: (record: RecordType, ...rest: any) => JSX.Element
    ellipsis?: boolean
    span: number
}

export interface InternalColumnType<RecordType> extends ResizableColumnType<RecordType> {
    width?: number
}

export type ResizeHandler = Exclude<ResizableProps['onResize'], undefined>

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
    const breakpoint = getActiveBreakpoint()
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

    function updateColumnWidth(index: number, width: number): void {
        const col = scrollWrapperRef.current?.querySelector(
            // nth-child is 1-indexed. first column is fixed. last column width must be uncontrolled.
            `.ant-table-content colgroup col:nth-child(${index + 2}):not(:last-child)`
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

    const handleColumnResize = (index: number): ResizeHandler => (_, { size: { width } }) => {
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
        if (timeout.current) {
            cancelAnimationFrame(timeout.current)
        }
        timeout.current = requestAnimationFrame(function () {
            const table = scrollWrapperRef.current?.querySelector('.ant-table table')
            const oldWidth = table?.clientWidth
            if (!oldWidth || oldWidth === newWidth) {
                return
            }
            setHeaderShouldRender(false)
            setHeaderColumns((cols) => {
                const lastIndex = initialColumns.length
                const nextColumns = cols.map((column, index) =>
                    index === lastIndex
                        ? column
                        : {
                              ...column,
                              width: Math.max(((column.width ?? 0) / oldWidth) * newWidth, minColumnWidth),
                          }
                )
                nextColumns.slice(0, lastIndex).forEach((col, index) => {
                    updateColumnWidth(index, col.width ?? minColumnWidth)
                })
                updateTableWidth()
                return nextColumns
            })
            setHeaderShouldRender(true)
            updateTableWidth()
        })
    }

    const resizeObserver = new ResizeObserver((entries) => {
        entries.forEach(({ contentRect: { width } }) => handleWrapperResize(width))
    })

    useLayoutEffect(() => {
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
                              render: initialColumns[index].render,
                              width: Math.max(columnSpanWidth * column.span, minColumnWidth),
                          }
                )
                setHeaderColumns(nextColumns)
                return nextColumns
            })
            updateScrollGradient()
            setHeaderShouldRender(true)
        }
    }, [initialColumns])

    return (
        <div ref={scrollWrapperRef} className="resizable-table-scroll-container" onScroll={updateScrollGradient}>
            <div ref={overlayRef} className="table-gradient-overlay">
                {headerShouldRender && (
                    <VirtualTableHeader
                        columns={headerColumns}
                        handleResize={handleColumnResize}
                        layoutEffect={updateTableWidth}
                        minColumnWidth={minColumnWidth}
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
