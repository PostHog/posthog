import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { HTMLProps, Reducer, useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { columnSort } from '../../../scenes/saved-insights/SavedInsights'
import { useResizeObserver } from '../../hooks/useResizeObserver'
import { IconChevronLeft, IconChevronRight } from '../icons'
import { LemonButton } from '../LemonButton'
import './LemonTable.scss'

/** 1 means ascending, -1 means descending. */
export type SortOrder = 1 | -1
/** Sorting state. */
export interface Sorting {
    columnIndex: number
    order: SortOrder
}

export interface LemonTableColumn<T extends Record<string, any>, D extends keyof T> {
    title?: string | React.ReactNode
    key?: keyof T
    dataIndex?: D
    render?: (dataValue: T[D] | undefined, record: T) => React.ReactNode | string | boolean | null | undefined
    sorter?: (a: T, b: T) => number
    className?: string
    /** Column content alignment. Left by default. Set to right for numerical values (amounts, days ago etc.) */
    align?: 'left' | 'right' | 'center'
    /** TODO: Whether the column should be sticky when scrolling */
    sticky?: boolean
    /** Set width. */
    width?: string | number
}

export type LemonTableColumns<T extends Record<string, any>> = LemonTableColumn<T, keyof T>[]

export interface LemonTableProps<T extends Record<string, any>> {
    /** Element key that will also be used in pagination to improve search param uniqueness. */
    key?: string
    columns: LemonTableColumns<T>
    dataSource: T[]
    /** Which column to use for the row key, as an alternative to the default row index mechanism. */
    rowKey?: keyof T
    /** Function that for each row determines what props should its `tr` element have based on the row's record. */
    onRow?: (record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    loading?: boolean
    pagination?: { pageSize: number; hideOnSinglePage?: boolean }
    /** Sorting order to start with. */
    defaultSorting?: Sorting
    /** What to show when there's no data. By default it's generic "No data" */
    emptyState?: React.ReactNode
    'data-attr'?: string
    /** Class name to append to each row */
    rowClassName?: string
}

export function LemonTable<T extends Record<string, any>>({
    key,
    columns,
    dataSource,
    rowKey,
    onRow,
    loading,
    pagination,
    defaultSorting,
    emptyState = 'No data',
    rowClassName,
    ...divProps
}: LemonTableProps<T>): JSX.Element {
    /** Search param that will be used for storing and syncing the current page */
    const currentPageParam = key ? `${key}_page` : 'page'

    const { location, searchParams, hashParams } = useValues(router)
    const { push } = useActions(router)

    // A tuple signaling scrollability, on the left and on the right respectively
    const [isScrollable, setIsScrollable] = useState([false, false])
    // Sorting state machine
    const [sortingState, sortingDispatch] = useReducer<Reducer<Sorting | null, Pick<Sorting, 'columnIndex'>>>(
        (state, action) => {
            if (!state || state.columnIndex !== action.columnIndex) {
                return { columnIndex: action.columnIndex, order: 1 }
            } else if (state.order === 1) {
                return { columnIndex: action.columnIndex, order: -1 }
            } else {
                return null
            }
        },
        defaultSorting || null
    )
    // Push a new browing history item to keep track of the current page
    const setCurrentPage = useCallback(
        (newPage: number) => push(location.pathname, { ...searchParams, [currentPageParam]: newPage }, hashParams),
        [location, searchParams, hashParams, push]
    )

    const scrollRef = useRef<HTMLDivElement>(null)

    /** Number of pages. */
    const pageCount = pagination ? Math.ceil(dataSource.length / pagination.pageSize) : 1
    /** Page adjusted for `pageCount` possibly having gotten smaller since last page param update. */
    const currentPage = Math.min(parseInt(searchParams[currentPageParam]) || 1, pageCount)
    /** Whether there's reason to show pagination. */
    const showPagination = pageCount > 1 || pagination?.hideOnSinglePage === true

    const updateIsScrollable = useCallback(() => {
        const element = scrollRef.current
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
        ref: scrollRef,
        onResize: updateIsScrollable,
    })

    useEffect(() => {
        const element = scrollRef.current
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
        const calculatedStartIndex = pagination ? (currentPage - 1) * pagination.pageSize : 0
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
            <div className="LemonTable__scroll" ref={scrollRef}>
                <div className="LemonTable__content">
                    <table>
                        <colgroup>
                            {columns.map(({ width }, index) => (
                                <col key={index} style={{ width }} />
                            ))}
                        </colgroup>
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
                                        key={`LemonTable-row-${rowKey ? data[rowKey] : currentStartIndex + rowIndex}`}
                                        data-row-key={rowKey ? data[rowKey] : rowIndex}
                                        {...onRow?.(data)}
                                        className={rowClassName}
                                    >
                                        {columns.map((column, columnIndex) => {
                                            const value = column.dataIndex ? data[column.dataIndex] : undefined
                                            const contents = column.render ? column.render(value, data) : value
                                            return (
                                                <td
                                                    key={
                                                        column.key
                                                            ? data[column.key]
                                                            : column.dataIndex
                                                            ? data[column.dataIndex]
                                                            : columnIndex
                                                    }
                                                    className={column.className}
                                                    style={{ textAlign: column.align }}
                                                >
                                                    {contents}
                                                </td>
                                            )
                                        })}
                                    </tr>
                                ))
                            ) : (
                                <tr>
                                    <td colSpan={columns.length}>{emptyState}</td>
                                </tr>
                            )}
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
                                onClick={() => setCurrentPage(Math.max(1, Math.min(pageCount, currentPage) - 1))}
                            />
                            <LemonButton
                                compact
                                icon={<IconChevronRight />}
                                type="stealth"
                                disabled={currentPage === pageCount}
                                onClick={() => setCurrentPage(Math.min(pageCount, currentPage + 1))}
                            />
                        </div>
                    )}
                    <div className="LemonTable__overlay" />
                    <div className="LemonTable__loader" />
                </div>
            </div>
        </div>
    )
}
