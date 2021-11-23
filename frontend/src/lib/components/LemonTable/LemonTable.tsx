import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { HTMLProps, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { columnSort } from '../../../scenes/saved-insights/SavedInsights'
import { useResizeObserver } from '../../hooks/useResizeObserver'
import { IconChevronLeft, IconChevronRight } from '../icons'
import { LemonButton } from '../LemonButton'
import { Tooltip } from '../Tooltip'
import './LemonTable.scss'

/** 1 means ascending, -1 means descending. */
export type SortOrder = 1 | -1
/** Sorting state. */
export interface Sorting {
    columnKey: string
    order: SortOrder
}

export interface PaginationAuto {
    pageSize: number
    hideOnSinglePage?: boolean
}

export interface PaginationManual extends PaginationAuto {
    currentPage: number
    entryCount: number
    onForward: () => void
    onBackward: () => void
}

export interface LemonTableColumn<T extends Record<string, any>, D extends keyof T> {
    title?: string | React.ReactNode
    key?: string
    dataIndex?: D
    render?: (dataValue: T[D] | undefined, record: T) => React.ReactNode | string | boolean | null | undefined
    /** Sorting function. Set to `true` if using manual pagination, in which case you'll also have to provide `sorting` on the table. */
    sorter?: ((a: T, b: T) => number) | true
    className?: string
    /** Column content alignment. Left by default. Set to right for numerical values (amounts, days ago etc.) */
    align?: 'left' | 'right' | 'center'
    /** TODO: Whether the column should be sticky when scrolling */
    sticky?: boolean
    /** Set width. */
    width?: string | number
}
export type LemonTableColumns<T extends Record<string, any>> = LemonTableColumn<T, keyof T>[]

/**
 * Determine the column's key, using `dataIndex` as fallback.
 * If `obligation` is specified, will throw an error if the key can't be determined.
 * */
function determineColumnKey(column: LemonTableColumn<any, any>, obligation: string): string
function determineColumnKey(column: LemonTableColumn<any, any>, obligation?: undefined): string | null
function determineColumnKey(column: LemonTableColumn<any, any>, obligation?: string): string | null {
    const columnKey = column.key || column.dataIndex
    if (obligation && !columnKey) {
        throw new Error(`LemonTable: Column \`key\` or \`dataIndex\` must be defined for ${obligation}`)
    }
    return columnKey
}

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
    pagination?: PaginationAuto | PaginationManual
    /**
     * By default sorting goes: 0. unsorted > 1. ascending > 2. descending > GOTO 0 (loop).
     * With sorting cancellation disabled, GOTO 0 is replaced by GOTO 1. */
    disableSortingCancellation?: boolean
    /** Sorting order to start with. */
    defaultSorting?: Sorting | null
    /** Controlled sort order. */
    sorting?: Sorting | null
    onSort?: (newSorting: Sorting | null) => void
    /** What to show when there's no data. The default value is generic `'No data'`. */
    emptyState?: React.ReactNode
    /** What to describe the entries as, singular and plural. The default value is `['entry', 'entries']`. */
    nouns?: [string, string]
    'data-attr'?: string
}

function getNextSorting(
    currentSorting: Sorting | null,
    selectedColumnKey: string,
    disableSortingCancellation: boolean
): Sorting | null {
    if (
        !currentSorting ||
        currentSorting.columnKey !== selectedColumnKey ||
        (currentSorting.order === -1 && disableSortingCancellation)
    ) {
        return { columnKey: selectedColumnKey, order: 1 }
    } else if (currentSorting.order === 1) {
        return { columnKey: selectedColumnKey, order: -1 }
    } else {
        return null
    }
}

export function LemonTable<T extends Record<string, any>>({
    key,
    columns,
    dataSource,
    rowKey,
    onRow,
    loading,
    pagination,
    disableSortingCancellation = false,
    defaultSorting = null,
    sorting,
    onSort,
    emptyState = 'No data',
    nouns = ['entry', 'entries'],
    'data-attr': dataAttr,
}: LemonTableProps<T>): JSX.Element {
    /** Search param that will be used for storing and syncing the current page */
    const currentPageParam = key ? `${key}_page` : 'page'

    const { location, searchParams, hashParams } = useValues(router)
    const { push } = useActions(router)

    // A tuple signaling scrollability, on the left and on the right respectively
    const [isScrollable, setIsScrollable] = useState([false, false])
    // Sorting state machine
    const [sortingState, setSortingState] = useState<Sorting | null>(defaultSorting)
    const currentSorting = sorting !== undefined ? sorting : sortingState

    // Push a new browing history item to keep track of the current page
    const setLocalCurrentPage = useCallback(
        (newPage: number) => push(location.pathname, { ...searchParams, [currentPageParam]: newPage }, hashParams),
        [location, searchParams, hashParams, push]
    )

    const scrollRef = useRef<HTMLDivElement>(null)

    /** Number of entries in total. */
    const entryCount = pagination && 'entryCount' in pagination ? pagination.entryCount : dataSource.length
    /** Number of pages. */
    const pageCount = pagination ? Math.ceil(entryCount / pagination.pageSize) : 1
    /** Page adjusted for `pageCount` possibly having gotten smaller since last page param update. */
    const currentPage =
        pagination && 'currentPage' in pagination
            ? pagination.currentPage
            : Math.min(parseInt(searchParams[currentPageParam]) || 1, pageCount)
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
        if (currentSorting) {
            const { columnKey: sortColumnKey, order: sortOrder } = currentSorting
            const sorter = columns.find(
                (searchColumn) => searchColumn.sorter && determineColumnKey(searchColumn, 'sorting') === sortColumnKey
            )?.sorter
            if (typeof sorter === 'function') {
                processedDataSource = processedDataSource.slice().sort((a, b) => sortOrder * sorter(a, b))
            }
        }
        const calculatedStartIndex = pagination ? (currentPage - 1) * pagination.pageSize : 0
        const calculatedFrame =
            pagination && !('currentPage' in pagination)
                ? processedDataSource.slice(calculatedStartIndex, calculatedStartIndex + pagination.pageSize)
                : processedDataSource
        const calculatedEndIndex = calculatedStartIndex + calculatedFrame.length
        return {
            currentFrame: calculatedFrame,
            currentStartIndex: calculatedStartIndex,
            currentEndIndex: calculatedEndIndex,
        }
    }, [currentPage, pageCount, pagination, dataSource, currentSorting])

    return (
        <div
            className={clsx(
                'LemonTable',
                loading && 'LemonTable--loading',
                showPagination && 'LemonTable--paginated',
                isScrollable[0] && 'LemonTable--scrollable-left',
                isScrollable[1] && 'LemonTable--scrollable-right'
            )}
            data-attr={dataAttr}
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
                                        key={determineColumnKey(column) || columnIndex}
                                        className={clsx(
                                            column.sorter && 'LemonTable__header--actionable',
                                            column.className
                                        )}
                                        style={{ textAlign: column.align }}
                                        onClick={
                                            column.sorter
                                                ? () => {
                                                      const nextSorting = getNextSorting(
                                                          currentSorting,
                                                          determineColumnKey(column, 'sorting'),
                                                          disableSortingCancellation
                                                      )
                                                      setSortingState(nextSorting)
                                                      onSort?.(nextSorting)
                                                  }
                                                : undefined
                                        }
                                    >
                                        <Tooltip
                                            title={
                                                column.sorter !== undefined
                                                    ? `Click to ${
                                                          currentSorting &&
                                                          currentSorting.columnKey ===
                                                              determineColumnKey(column, 'sorting')
                                                              ? currentSorting.order === 1
                                                                  ? 'sort descending'
                                                                  : 'cancel sorting'
                                                              : 'sort ascending'
                                                      }`
                                                    : null
                                            }
                                        >
                                            {' '}
                                            <div className="LemonTable__header-content">
                                                {column.title}
                                                {column.sorter &&
                                                    columnSort(
                                                        currentSorting &&
                                                            currentSorting.columnKey ===
                                                                determineColumnKey(column, 'sorting')
                                                            ? currentSorting.order === 1
                                                                ? 'up'
                                                                : 'down'
                                                            : 'none'
                                                    )}
                                            </div>
                                        </Tooltip>
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {entryCount ? (
                                currentFrame.map((data, rowIndex) => (
                                    <tr
                                        key={`LemonTable-row-${rowKey ? data[rowKey] : currentStartIndex + rowIndex}`}
                                        data-row-key={rowKey ? data[rowKey] : rowIndex}
                                        {...onRow?.(data)}
                                    >
                                        {columns.map((column, columnIndex) => {
                                            const columnKeyRaw = column.key || column.dataIndex
                                            const columnKeyOrIndex = columnKeyRaw ? String(columnKeyRaw) : columnIndex
                                            const value = column.dataIndex ? data[column.dataIndex] : undefined
                                            const contents = column.render ? column.render(value, data) : value
                                            return (
                                                <td
                                                    key={columnKeyOrIndex}
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
                                    ? `No ${nouns[1]}`
                                    : currentFrame.length === 1
                                    ? `${currentEndIndex} of ${entryCount} ${entryCount === 1 ? nouns[0] : nouns[1]}`
                                    : `${currentStartIndex + 1}-${currentEndIndex} of ${entryCount} ${nouns[1]}`}
                            </span>
                            <LemonButton
                                compact
                                icon={<IconChevronLeft />}
                                type="stealth"
                                disabled={currentPage === 1}
                                onClick={
                                    pagination && 'onBackward' in pagination
                                        ? pagination.onBackward
                                        : () => setLocalCurrentPage(Math.max(1, Math.min(pageCount, currentPage) - 1))
                                }
                            />
                            <LemonButton
                                compact
                                icon={<IconChevronRight />}
                                type="stealth"
                                disabled={currentPage === pageCount}
                                onClick={
                                    pagination && 'onForward' in pagination
                                        ? pagination.onForward
                                        : () => setLocalCurrentPage(Math.min(pageCount, currentPage + 1))
                                }
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
