import clsx from 'clsx'
import React, { HTMLProps, Reducer, useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { columnSort } from '../../../scenes/saved-insights/SavedInsights'
import { useResizeObserver } from '../../hooks/useResizeObserver'
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

/** 1 means ascending, -1 means descending. */
type SortOrder = 1 | -1

export function LemonTable<T extends Record<string, any>>({
    columns,
    dataSource,
    rowKey,
    onRow,
    loading,
    pagination,
    ...divProps
}: LemonTableProps<T>): JSX.Element {
    const [isScrollable, setIsScrollable] = useState([false, false]) // Left and right
    const [currentPage, setCurrentPage] = useState(1)
    const [sortingState, sortingDispatch] = useReducer<
        Reducer<{ columnIndex: number; order: SortOrder } | null, { columnIndex: number }>
    >((state, action) => {
        if (!state || state.columnIndex !== action.columnIndex) {
            return { columnIndex: action.columnIndex, order: 1 }
        } else if (state.order === 1) {
            return { columnIndex: action.columnIndex, order: -1 }
        } else {
            return null
        }
    }, null)

    const contentRef = useRef<HTMLDivElement>(null)

    const pageCount = pagination ? Math.ceil(dataSource.length / pagination.pageSize) : 1
    const showPagination = pageCount > 1 || pagination?.hideOnSinglePage === true

    const updateIsScrollable = useCallback(() => {
        const element = contentRef.current
        if (element) {
            const left = element.scrollLeft > 0
            const right =
                element.scrollWidth > element.clientWidth &&
                element.scrollWidth > element.scrollLeft + element.clientWidth
            if (left !== isScrollable[0] || right !== isScrollable[1]) {
                setIsScrollable([left, right])
            }
        }
    }, [isScrollable])

    useResizeObserver({
        ref: contentRef,
        onResize: updateIsScrollable,
    })

    useEffect(() => {
        const element = contentRef.current
        if (element) {
            element.addEventListener('scroll', updateIsScrollable)
            return () => element.removeEventListener('scroll', updateIsScrollable)
        }
    }, [updateIsScrollable])

    const { currentFrame, currentStartIndex, currentEndIndex } = useMemo(() => {
        let processedDataSource = dataSource
        if (sortingState) {
            const sorter = columns[sortingState.columnIndex].sorter
            if (sorter) {
                processedDataSource = processedDataSource.slice().sort((a, b) => sortingState.order * sorter(a, b))
            }
        }
        const calculatedStartIndex = pagination ? (Math.min(currentPage, pageCount) - 1) * pagination.pageSize : 0
        const calculatedFrame = pagination
            ? processedDataSource.slice(calculatedStartIndex, calculatedStartIndex + pagination.pageSize)
            : processedDataSource
        const calculatedEndIndex = calculatedStartIndex + calculatedFrame.length
        return {
            currentFrame: calculatedFrame,
            currentStartIndex: calculatedStartIndex,
            currentEndIndex: calculatedEndIndex,
        }
    }, [currentPage, pageCount, pagination, dataSource, sortingState])

    return (
        <div
            className={clsx(
                'LemonTable',
                loading && 'LemonTable--loading',
                showPagination && 'LemonTable--paginated',
                isScrollable[0] && 'LemonTable--scrollable-left',
                isScrollable[1] && 'LemonTable--scrollable-right'
            )}
            {...divProps}
        >
            <div className="LemonTable__content" ref={contentRef}>
                <table>
                    <thead>
                        <tr>
                            {columns.map((column, columnIndex) => (
                                <th
                                    key={columnIndex}
                                    className={clsx(
                                        column.sorter && 'LemonTable__header--actionable',
                                        column.className
                                    )}
                                    style={{ textAlign: column.align }}
                                    onClick={column.sorter ? () => sortingDispatch({ columnIndex }) : undefined}
                                >
                                    <div className="LemonTable__header-content">
                                        {column.title}
                                        {column.sorter &&
                                            columnSort(
                                                sortingState && sortingState.columnIndex === columnIndex
                                                    ? sortingState.order === 1
                                                        ? 'up'
                                                        : 'down'
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
                                <tr
                                    key={`LemonTable-row-${rowKey ? data[rowKey] : rowIndex}`}
                                    data-row-key={rowKey ? data[rowKey] : rowIndex}
                                    {...onRow?.(data)}
                                >
                                    {columns.map((column, columnIndex) => (
                                        <td
                                            key={columnIndex}
                                            className={column.className}
                                            style={{ textAlign: column.align }}
                                        >
                                            {column.render
                                                ? column.render(
                                                      column.dataIndex ? data[column.dataIndex] : undefined,
                                                      data
                                                  )
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
        </div>
    )
}
