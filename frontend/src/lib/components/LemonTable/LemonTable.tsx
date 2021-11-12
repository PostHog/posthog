import React, { HTMLProps } from 'react'
import './LemonTable.scss'

export interface LemonTableColumn<T extends Record<string, any>, D extends keyof T> {
    title: string | React.ReactNode
    key?: keyof T
    dataIndex?: D
    render?: (dataValue: T[D] | undefined, record: T) => React.ReactNode
    sorter?: (a: T, b: T) => number
    span?: number

    width?: string | number
    className?: string
    fixed?: 'left' | 'right'
    align?: 'left' | 'right'
}

export type LemonTableColumns<T extends Record<string, any>> = LemonTableColumn<T, keyof T>[]

export interface LemonTableProps<T extends Record<string, any>> {
    columns: LemonTableColumns<T>
    dataSource: T[]
    rowKey?: string
    onRow?: (record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    'data-attr'?: string
}

export function LemonTable<T extends Record<string, any>>({
    columns,
    dataSource,
    rowKey,
    onRow,
    ...divProps
}: LemonTableProps<T>): JSX.Element {
    return (
        <div className="LemonTable" {...divProps}>
            <table>
                <thead>
                    <tr>
                        {columns.map((headerCol, headerColIndex) => (
                            <th key={headerColIndex} className={headerCol.className}>
                                {headerCol.title}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {dataSource.map((data, rowIndex) => (
                        <tr key={`LemonTable-row-${rowKey ? data[rowKey] : rowIndex}`} {...onRow?.(data)}>
                            {columns.map((rowCol, rowColIndex) => (
                                <td key={rowColIndex} className={rowCol.className} align={rowCol.align}>
                                    {rowCol.render
                                        ? rowCol.render(rowCol.dataIndex ? data[rowCol.dataIndex] : undefined, data)
                                        : rowCol.dataIndex
                                        ? data[rowCol.dataIndex]
                                        : undefined}
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
