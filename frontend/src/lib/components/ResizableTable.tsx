import React, { useEffect, useState } from 'react'
import { Table, TableProps } from 'antd'
import { Resizable } from 'react-resizable'

function ResizableTitle(props: any): JSX.Element {
    const { onResize, width, ...restProps } = props

    if (!width) {
        return <th {...restProps} />
    }

    return (
        <Resizable // TODO min width
            width={width}
            height={0}
            handle={
                <span
                    style={{
                        position: 'absolute',
                        right: '-5px',
                        bottom: 0,
                        zIndex: 1,
                        width: '10px',
                        height: '100%',
                        cursor: 'col-resize',
                    }}
                    onClick={(e) => {
                        e.stopPropagation()
                    }}
                />
            }
            onResize={onResize}
            draggableOpts={{ enableUserSelectHack: false }}
        >
            <th {...restProps} />
        </Resizable>
    )
}

// Type matches antd.Table
// eslint-disable-next-line @typescript-eslint/ban-types
export function ResizableTable<RecordType extends object = any>({
    columns: initialColumns,
    components,
    ...props
}: TableProps<RecordType>): JSX.Element {
    const handleResize = (index: number) => (_: unknown, { size: { width } }: { size: { width: number } }) => {
        // TODO type
        setColumns((columns) => {
            const nextColumns = [...columns]
            nextColumns[index] = {
                ...nextColumns[index],
                width,
            }
            return nextColumns
        })
    }
    const [columns, setColumns] = useState(() =>
        (initialColumns ?? []).map((col, index) => {
            console.log(col)
            return {
                ...col,
                width: index === 0 ? undefined : 100, // TODO: bugfix the fact that at least 1 col must be uncontrolled
                onHeaderCell: (column) => ({
                    // TODO type
                    width: column.width ?? 100,
                    onResize: handleResize(index),
                }),
            }
        })
    )
    useEffect(() => {
        // TODO run on first render to determine default DOM sizing
    })
    return (
        <Table
            columns={columns} // TODO type
            components={{
                ...components,
                header: {
                    ...(components?.header || {}),
                    cell: ResizableTitle,
                },
            }}
            {...props}
        />
    )
}
