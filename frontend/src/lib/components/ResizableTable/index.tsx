import React, { useLayoutEffect, useRef, useState } from 'react'
import { Table, TableProps } from 'antd'
import { Resizable } from 'react-resizable'
import { getActiveBreakpoint, getFullwidthColumnSize, getMaxColumnWidth, getMinColumnWidth } from './responsiveUtils'

import './index.scss'

export interface ResizableColumnType<RecordType> {
    title: string | JSX.Element
    key?: string
    render: (record: RecordType) => JSX.Element
    ellipsis?: boolean
    span: number
}

function ResizableTitle(props: any): JSX.Element {
    const { children, onResize, width, minConstraints, maxConstraints, ...restProps } = props
    if (!width) {
        return <th {...restProps} />
    }
    const [isDragging, setIsDragging] = useState(false)
    return (
        <Resizable
            width={width}
            height={0}
            minConstraints={minConstraints}
            maxConstraints={maxConstraints}
            axis="x"
            handle={<span className="resizable-handle" data-drag-active={isDragging} />}
            onResize={onResize}
            onResizeStart={(e) => {
                e.preventDefault()
                setIsDragging(true)
            }}
            onResizeStop={() => setIsDragging(false)}
            draggableOpts={{ enableUserSelectHack: false }}
        >
            <th {...restProps}>
                <div className="th-inner-wrapper">{children}</div>
            </th>
        </Resizable>
    )
}

interface ResizableTableProps<RecordType> extends TableProps<RecordType> {
    columns: ResizableColumnType<RecordType>[]
}

interface InternalColumnType<RecordType> extends ResizableColumnType<RecordType> {
    onHeaderCell: (props: any) => React.HTMLAttributes<HTMLElement>
    width: number
}

// Type matches antd.Table
export function ResizableTable<RecordType extends Record<any, any> = any>({
    columns: initialColumns = [],
    components,
    ...props
}: ResizableTableProps<RecordType>): JSX.Element {
    const breakpoint = getActiveBreakpoint()
    const minConstraints = [getMinColumnWidth(breakpoint), 0]
    const maxConstraints = [getMaxColumnWidth(breakpoint), 0]
    const scrollWrapperRef = useRef<HTMLDivElement>(null)
    const overlayRef = useRef<HTMLDivElement>(null)
    function getTotalWidth(columns: InternalColumnType<RecordType>[]): number {
        return columns.reduce((total, current) => total + current.width, 0)
    }
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
    const handleResize = (index: number) => (_: unknown, { size: { width } }: { size: { width: number } }) => {
        setColumns((columns: InternalColumnType<RecordType>[]) => {
            const nextColumns = [...columns]
            nextColumns[index] = {
                ...nextColumns[index],
                width,
            }
            return nextColumns
        })
        updateScrollGradient()
    }
    const [columns, setColumns] = useState(() => {
        const defaultColumnWidth = getFullwidthColumnSize({})
        return initialColumns.map(
            (column, index) =>
                ({
                    ...column,
                    width: defaultColumnWidth,
                    onHeaderCell: ({ width }: { width: number }) => ({
                        onResize: handleResize(index),
                        minConstraints,
                        maxConstraints,
                        width,
                    }),
                } as InternalColumnType<RecordType>)
        )
    })
    useLayoutEffect(() => {
        // Calculate relative column widths (px) once the wrapper is mounted.
        if (scrollWrapperRef.current) {
            const wrapperWidth = scrollWrapperRef.current.clientWidth
            const columnWidth = getFullwidthColumnSize({
                wrapperWidth,
                breakpoint,
            })
            setColumns((cols) => {
                const nextColumns = cols.map((column) => ({
                    ...column,
                    width: columnWidth * column.span,
                }))
                if (getTotalWidth(nextColumns) > wrapperWidth) {
                    setScrollableRight(true)
                }
                return nextColumns
            })
        }
    }, [])
    return (
        <div ref={scrollWrapperRef} className="resizable-table-scroll-container" onScroll={updateScrollGradient}>
            <div ref={overlayRef} className="table-gradient-overlay">
                <Table
                    columns={columns}
                    components={{
                        ...components,
                        header: {
                            ...components?.header,
                            cell: ResizableTitle,
                        },
                    }}
                    tableLayout="fixed"
                    {...props}
                />
            </div>
        </div>
    )
}
