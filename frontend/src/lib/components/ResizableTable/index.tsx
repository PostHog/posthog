import React, { useState } from 'react'
import { Table, TableProps } from 'antd'
import { Resizable } from 'react-resizable'
import { SessionType } from '~/types'
import { getActiveBreakpoint, getFullwidthColumnSize, getMaxColumnWidth, getMinColumnWidth } from './responsiveUtils'

import './index.scss'

export type ResizableColumnType = {
    title: string | JSX.Element
    key?: string
    render: (session: SessionType) => JSX.Element
    ellipsis?: boolean
    span: number
}

type InternalColumnType = ResizableColumnType & {
    onHeaderCell: (props: any) => React.HTMLAttributes<HTMLElement>
    width: number
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

// Type matches antd.Table
// eslint-disable-next-line @typescript-eslint/ban-types
export function ResizableTable<RecordType extends object = any>({
    columns: initialColumns = [],
    components,
    ...props
}: Omit<TableProps<RecordType>, 'columns'> & { columns: ResizableColumnType[] }): JSX.Element {
    const handleResize = (index: number) => (_: unknown, { size: { width } }: { size: { width: number } }) => {
        setColumns((columns: InternalColumnType[]) => {
            const nextColumns = [...columns]
            nextColumns[index] = {
                ...nextColumns[index],
                width,
            }
            return nextColumns
        })
    }
    const breakpoint = getActiveBreakpoint()
    const minConstraints = [getMinColumnWidth(breakpoint, window.innerWidth), 0]
    const maxConstraints = [getMaxColumnWidth(breakpoint, window.innerWidth), 0]
    const [columns, setColumns] = useState(() =>
        initialColumns.map(
            (column, index) =>
                ({
                    ...column,
                    width: getFullwidthColumnSize(column.span, breakpoint),
                    onHeaderCell: ({ width }: { width: number }) => ({
                        onResize: handleResize(index),
                        minConstraints,
                        maxConstraints,
                        width,
                    }),
                } as InternalColumnType)
        )
    )
    return (
        <div className="resizable-table-scroll-container">
            <Table
                columns={columns}
                components={{
                    ...components,
                    header: {
                        ...(components?.header || {}),
                        cell: ResizableTitle,
                    },
                }}
                tableLayout="fixed"
                {...props}
            />
        </div>
    )
}
