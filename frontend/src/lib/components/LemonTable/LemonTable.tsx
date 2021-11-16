import clsx from 'clsx'
import React, { HTMLProps } from 'react'
import './LemonTable.scss'

export interface LemonTableColumn<T extends Record<string, any>, D extends keyof T> {
    title?: string | React.ReactNode
    key?: keyof T
    dataIndex?: D
    render?: (dataValue: T[D] | undefined, record: T) => React.ReactNode
    sorter?: (a: T, b: T) => number
    span?: number
    className?: string
    /** Column content alignment. Left by default. Set to right for numerical values (amounts, days ago etc.) */
    align?: 'left' | 'right' | 'center'
    /** TODO: Whether the column should be sticky when scrolling */
    sticky?: boolean
    /** TODO: Set width */
    width?: string | number
}

export type LemonTableColumns<T extends Record<string, any>> = LemonTableColumn<T, keyof T>[]

export interface LemonTableProps<T extends Record<string, any>> {
    columns: LemonTableColumns<T>
    dataSource: T[]
    rowKey?: string
    onRow?: (record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    'data-attr'?: string
}

function isHorizontallyScrollable(element: HTMLElement): boolean {
    return element.scrollWidth > element.clientWidth
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
                            <th
                                key={headerColIndex}
                                className={clsx(headerCol.sticky && 'LemonTable__cell--sticky', headerCol.className)}
                                style={{ textAlign: headerCol.align }}
                            >
                                {headerCol.title}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {dataSource.map((data, rowIndex) => (
                        <tr key={`LemonTable-row-${rowKey ? data[rowKey] : rowIndex}`} {...onRow?.(data)}>
                            {columns.map((rowCol, rowColIndex) => (
                                <td
                                    key={rowColIndex}
                                    className={clsx(rowCol.sticky && 'LemonTable__cell--sticky', rowCol.className)}
                                    style={{ textAlign: rowCol.align }}
                                >
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
