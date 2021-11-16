import clsx from 'clsx'
import React, { HTMLProps, useState } from 'react'
import { IconChevronLeft, IconChevronRight } from '../icons'
import { LemonButton } from '../LemonButton'
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
    loading?: boolean
    pagination?: { pageSize: number; hideOnSinglePage?: boolean }
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
    loading,
    pagination,
    ...divProps
}: LemonTableProps<T>): JSX.Element {
    const [currentPage, setCurrentPage] = useState(1)

    const pageCount = pagination ? Math.ceil(dataSource.length / pagination.pageSize) : 1
    const showPagination = pageCount > 1 || pagination?.hideOnSinglePage === true
    const currentStartIndex = pagination ? (Math.min(currentPage, pageCount) - 1) * pagination.pageSize : 0
    const currentFrame = pagination
        ? dataSource.slice(currentStartIndex, currentStartIndex + pagination.pageSize)
        : dataSource
    const currentEndIndex = currentStartIndex + currentFrame.length

    return (
        <div className={clsx('LemonTable', showPagination && 'LemonTable--paginated')} {...divProps}>
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
                    {currentFrame.map((data, rowIndex) => (
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
            {showPagination && (
                <div className="LemonTable__pagination">
                    <span className="LemonTable__locator">
                        {currentFrame.length === 0
                            ? 'No entries'
                            : currentFrame.length === 1
                            ? `${currentEndIndex} of ${dataSource.length} entries`
                            : `${currentStartIndex + 1}-${currentEndIndex} of ${dataSource.length} entries`}
                    </span>
                    <LemonButton
                        compact
                        icon={<IconChevronLeft />}
                        type="stealth"
                        disabled={currentPage === 1}
                        onClick={() => setCurrentPage((state) => Math.max(1, Math.min(pageCount, state) - 1))}
                    />
                    <LemonButton
                        compact
                        icon={<IconChevronRight />}
                        type="stealth"
                        disabled={currentPage === pageCount}
                        onClick={() => setCurrentPage((state) => Math.min(pageCount, state + 1))}
                    />
                </div>
            )}
        </div>
    )
}
