import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { HTMLProps, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useResizeObserver } from '../../hooks/useResizeObserver'
import { IconChevronLeft, IconChevronRight } from '../icons'
import { LemonButton } from '../LemonButton'
import { Tooltip } from '../Tooltip'
import { TableRow } from './components'
import './LemonTable.scss'
import { Sorting, SortingIndicator, getNextSorting } from './sorting'
import { ExpandableConfig, LemonTableColumn, LemonTableColumns, PaginationAuto, PaginationManual } from './types'
export { Sorting, SortOrder } from './sorting'
export { ExpandableConfig, LemonTableColumn, LemonTableColumns, PaginationAuto, PaginationManual } from './types'

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
    expandable?: ExpandableConfig<T>
    /**
     * By default sorting goes: 0. unsorted > 1. ascending > 2. descending > GOTO 0 (loop).
     * With sorting cancellation disabled, GOTO 0 is replaced by GOTO 1. */
    disableSortingCancellation?: boolean
    /** Sorting order to start with. */
    defaultSorting?: Sorting | null
    /** Controlled sort order. */
    sorting?: Sorting | null
    /** Sorting change handler for controlled sort order. */
    onSort?: (newSorting: Sorting | null) => void
    /** What to show when there's no data. The default value is generic `'No data'`. */
    emptyState?: React.ReactNode
    /** What to describe the entries as, singular and plural. The default value is `['entry', 'entries']`. */
    nouns?: [string, string]
    className?: string
    'data-attr'?: string
    /** Class name to append to each row */
    rowClassName?: string
}

export function LemonTable<T extends Record<string, any>>({
    key,
    columns,
    dataSource,
    rowKey,
    rowClassName,
    onRow,
    loading,
    pagination,
    expandable,
    disableSortingCancellation = false,
    defaultSorting = null,
    sorting,
    onSort,
    emptyState = 'No data',
    nouns = ['entry', 'entries'],
    className,
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
    const entryCount: number | null = pagination?.controlled ? pagination.entryCount || null : dataSource.length
    /** Number of pages. */
    const pageCount: number | null =
        entryCount && (pagination ? (pagination.pageSize ? Math.ceil(entryCount / pagination.pageSize) : 1) : null)
    /** Page adjusted for `pageCount` possibly having gotten smaller since last page param update. */
    const currentPage: number | null = pagination?.controlled
        ? pagination.currentPage || null
        : Math.min(parseInt(searchParams[currentPageParam]) || 1, pageCount as number)
    /** Whether pages previous and next are available. */
    const isPreviousAvailable: boolean =
        currentPage !== null ? currentPage > 1 : !!(pagination?.controlled && pagination.onBackward)
    const isNextAvailable: boolean =
        currentPage !== null && pageCount !== null
            ? currentPage < pageCount
            : !!(pagination?.controlled && pagination.onForward)
    /** Whether there's reason to show pagination. */
    const showPagination: boolean = isPreviousAvailable || isNextAvailable || pagination?.hideOnSinglePage === false

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
        const calculatedStartIndex =
            pagination && currentPage && pagination.pageSize ? (currentPage - 1) * pagination.pageSize : 0
        const calculatedFrame =
            pagination && !pagination.controlled
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
                isScrollable[1] && 'LemonTable--scrollable-right',
                className
            )}
            data-attr={dataAttr}
        >
            <div className="LemonTable__scroll" ref={scrollRef}>
                <div className="LemonTable__content">
                    <table>
                        <colgroup>
                            {expandable && <col style={{ width: 0 }} />}
                            {columns.map(({ width }, index) => (
                                <col key={index} style={{ width }} />
                            ))}
                        </colgroup>
                        <thead>
                            <tr>
                                {expandable && <th />}
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
                                                column.sorter &&
                                                (() => {
                                                    const nextSorting = getNextSorting(
                                                        currentSorting,
                                                        determineColumnKey(column, 'sorting'),
                                                        disableSortingCancellation
                                                    )
                                                    return `Click to ${
                                                        nextSorting
                                                            ? nextSorting.order === 1
                                                                ? 'sort ascending'
                                                                : 'sort descending'
                                                            : 'cancel sorting'
                                                    }`
                                                })
                                            }
                                        >
                                            {' '}
                                            <div className="LemonTable__header-content">
                                                {column.title}
                                                {column.sorter && (
                                                    <SortingIndicator
                                                        order={currentSorting ? currentSorting.order : null}
                                                    />
                                                )}
                                            </div>
                                        </Tooltip>
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {currentFrame ? (
                                currentFrame.map((record, rowIndex) => (
                                    <TableRow
                                        key={`LemonTable-row-${rowKey ? record[rowKey] : currentStartIndex + rowIndex}`}
                                        record={record}
                                        recordIndex={currentStartIndex + rowIndex}
                                        rowKey={rowKey}
                                        rowClassName={rowClassName}
                                        columns={columns}
                                        onRow={onRow}
                                        expandable={expandable}
                                    />
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
                                    : entryCount === null
                                    ? `${currentFrame.length} ${
                                          currentFrame.length === 1 ? nouns[0] : nouns[1]
                                      } on this page`
                                    : currentFrame.length === 1
                                    ? `${currentEndIndex} of ${entryCount} ${entryCount === 1 ? nouns[0] : nouns[1]}`
                                    : `${currentStartIndex + 1}-${currentEndIndex} of ${entryCount} ${nouns[1]}`}
                            </span>
                            <LemonButton
                                compact
                                icon={<IconChevronLeft />}
                                type="stealth"
                                disabled={!isPreviousAvailable}
                                onClick={
                                    pagination?.controlled
                                        ? pagination.onBackward
                                        : () =>
                                              setLocalCurrentPage(
                                                  Math.max(1, Math.min(pageCount as number, currentPage as number) - 1)
                                              )
                                }
                            />
                            <LemonButton
                                compact
                                icon={<IconChevronRight />}
                                type="stealth"
                                disabled={!isNextAvailable}
                                onClick={
                                    pagination?.controlled
                                        ? pagination.onForward
                                        : () =>
                                              setLocalCurrentPage(
                                                  Math.min(pageCount as number, (currentPage as number) + 1)
                                              )
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
