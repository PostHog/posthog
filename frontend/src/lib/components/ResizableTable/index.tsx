import React, { useState } from 'react'
import { Table, TableProps } from 'antd'
import { Resizable } from 'react-resizable'

import './index.scss'
import { SessionType } from '~/types'

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

function useFullwidthColumnSize(span: number = 1): number {
    const { innerWidth: width } = window
    return Math.floor(((width - 176) / 24) * span)
}

function ResizableTitle(props: any): JSX.Element {
    const { children, onResize, width, ...restProps } = props
    if (!width) {
        return <th {...restProps} />
    }
    const [isDragging, setIsDragging] = useState(false)
    return (
        <Resizable
            width={width}
            height={0}
            minConstraints={[useFullwidthColumnSize(1), 0]}
            maxConstraints={[useFullwidthColumnSize(12), 0]}
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
    columns: initialColumns,
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
    console.log(useFullwidthColumnSize(2))
    const [columns, setColumns] = useState(() =>
        (initialColumns ?? []).map((column, index) => {
            return {
                ...column,
                width: useFullwidthColumnSize(column.span),
                onHeaderCell: ({ width }: { width: number }) => ({
                    onResize: handleResize(index),
                    width,
                }),
            } as InternalColumnType
        })
    )
    return (
        <div className="resizable-table-scroll-container">
            <Table
                columns={columns} // TODO type
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
