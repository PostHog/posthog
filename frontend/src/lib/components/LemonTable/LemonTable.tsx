import clsx from 'clsx'
import React, { HTMLProps, useMemo, useReducer, useState } from 'react'
import { columnSort } from '../../../scenes/saved-insights/SavedInsights'
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

/** 0 means unsorted, 1 means ascending, -1 means descending. */
type SortOrder = 0 | 1 | -1

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
    const [sortOrdersState, sortOrdersDispatch] = useReducer(
        (state: Record<number, SortOrder>, action: { columnIndex: number }) => {
            let nextValue: SortOrder
            switch (state[action.columnIndex]) {
                case 1:
                    nextValue = -1
                    break
                case -1:
                    nextValue = 0
                    break
                default:
                    nextValue = 1
                    break
            }
            return {
                ...state,
                [action.columnIndex]: nextValue,
            }
        },
        {}
    )

    const pageCount = pagination ? Math.ceil(dataSource.length / pagination.pageSize) : 1
    const showPagination = pageCount > 1 || pagination?.hideOnSinglePage === true

    const { currentFrame, currentStartIndex, currentEndIndex } = useMemo(() => {
        const sortedDataSource = dataSource.slice().sort((a, b) => {
            let result = 0
            for (let i = 0; i < columns.length; i++) {
                const sorter = columns[i].sorter
                const sortOrder = sortOrdersState[i]
                if (sorter && sortOrder) {
                    result = sorter(a, b) * sortOrder
                    if (result !== 0) {
                        break
                    }
                }
            }
            return result
        })
        const calculatedStartIndex = pagination ? (Math.min(currentPage, pageCount) - 1) * pagination.pageSize : 0
        const calculatedFrame = pagination
            ? sortedDataSource.slice(calculatedStartIndex, calculatedStartIndex + pagination.pageSize)
            : sortedDataSource
        const calculatedEndIndex = calculatedStartIndex + calculatedFrame.length
        return {
            currentFrame: calculatedFrame,
            currentStartIndex: calculatedStartIndex,
            currentEndIndex: calculatedEndIndex,
        }
    }, [currentPage, pageCount, pagination, dataSource, sortOrdersState])

    return (
        <div
            className={clsx('LemonTable', loading && 'LemonTable--loading', showPagination && 'LemonTable--paginated')}
            {...divProps}
        >
            <table>
                <thead>
                    <tr>
                        {columns.map((column, columnIndex) => (
                            <th
                                key={columnIndex}
                                className={clsx(
                                    column.sorter && 'LemonTable__header--actionable',
                                    column.sticky && 'LemonTable__cell--sticky',
                                    column.className
                                )}
                                style={{ textAlign: column.align }}
                                onClick={column.sorter ? () => sortOrdersDispatch({ columnIndex }) : undefined}
                            >
                                <div className="LemonTable__header-content">
                                    {column.title}
                                    {column.sorter &&
                                        columnSort(
                                            sortOrdersState[columnIndex] === -1
                                                ? 'down'
                                                : sortOrdersState[columnIndex] === 1
                                                ? 'up'
                                                : 'none'
                                        )}
                                </div>
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {dataSource.length ? (
                        currentFrame.map((data, rowIndex) => (
                            <tr key={`LemonTable-row-${rowKey ? data[rowKey] : rowIndex}`} {...onRow?.(data)}>
                                {columns.map((column, columnIndex) => (
                                    <td
                                        key={columnIndex}
                                        className={clsx(column.sticky && 'LemonTable__cell--sticky', column.className)}
                                        style={{ textAlign: column.align }}
                                    >
                                        {column.render
                                            ? column.render(column.dataIndex ? data[column.dataIndex] : undefined, data)
                                            : column.dataIndex
                                            ? data[column.dataIndex]
                                            : undefined}
                                    </td>
                                ))}
                            </tr>
                        ))
                    ) : (
                        <tr>
                            <td colSpan={columns.length}>No data</td>
                        </tr>
                    )}
                </tbody>
            </table>
            <div className="LemonTable__loader" />
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
