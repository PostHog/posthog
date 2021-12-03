import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { HTMLProps, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useResizeObserver } from '../../hooks/useResizeObserver'
import { IconChevronLeft, IconChevronRight } from '../icons'
import { LemonButton } from '../LemonButton'
import { Tooltip } from '../Tooltip'
import { TableRow } from './TableRow'
import './LemonTable.scss'
import { Sorting, SortingIndicator, getNextSorting } from './sorting'
import { ExpandableConfig, LemonTableColumn, LemonTableColumns, PaginationAuto, PaginationManual } from './types'

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
    /** Table ID that will also be used in pagination to add uniqueness to search params (page + order). */
    id?: string
    columns: LemonTableColumns<T>
    dataSource: T[]
    /** Which column to use for the row key, as an alternative to the default row index mechanism. */
    rowKey?: keyof T | ((record: T) => string | number)
    /** Class name to append to each row */
    rowClassName?: string | ((record: T) => string)
    /** Function that for each row determines what props should its `tr` element have based on the row's record. */
    onRow?: (record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    /** Whether the header should be shown. The default value is `"middle"`. */
    size?: 'small' | 'middle'
    /** An embedded table has no border around it and no background. This way it blends better into other components. */
    embedded?: boolean
    loading?: boolean
    pagination?: PaginationAuto | PaginationManual
    expandable?: ExpandableConfig<T>
    /** Whether the header should be shown. The default value is `true`. */
    showHeader?: boolean
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
    /** What to show when there's no data. */
    emptyState?: React.ReactNode
    /** What to describe the entries as, singular and plural. The default value is `['entry', 'entries']`. */
    nouns?: [string, string]
    className?: string
    'data-attr'?: string
}

export function LemonTable<T extends Record<string, any>>({
    id,
    columns,
    dataSource,
    rowKey,
    rowClassName,
    onRow,
    size,
    embedded = false,
    loading,
    pagination,
    expandable,
    showHeader = true,
    disableSortingCancellation = false,
    defaultSorting = null,
    sorting,
    onSort,
    emptyState,
    nouns = ['entry', 'entries'],
    className,
    'data-attr': dataAttr,
}: LemonTableProps<T>): JSX.Element {
    /** Search param that will be used for storing and syncing the current page */
    const currentPageParam = id ? `${id}_page` : 'page'
    /** Search param that will be used for storing and syncing sorting */
    const currentSortingParam = id ? `${id}_order` : 'order'

    const { location, searchParams, hashParams } = useValues(router)
    const { push } = useActions(router)

    // A tuple signaling scrollability, on the left and on the right respectively
    const [isScrollable, setIsScrollable] = useState([false, false])

    /** Push a new browing history item to keep track of the current page */
    const setLocalCurrentPage = useCallback(
        (newPage: number) => push(location.pathname, { ...searchParams, [currentPageParam]: newPage }, hashParams),
        [location, searchParams, hashParams, push]
    )
    /** Replace the current browsing history item to change sorting */
    const setLocalSorting = useCallback(
        (newSorting: Sorting | null) =>
            push(
                location.pathname,
                {
                    ...searchParams,
                    [currentSortingParam]: newSorting
                        ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                        : undefined,
                },
                hashParams
            ),
        [location, searchParams, hashParams, push]
    )

    const scrollRef = useRef<HTMLDivElement>(null)
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
    }, [isScrollable[0], isScrollable[1]])
    const { width } = useResizeObserver({
        ref: scrollRef,
    })
    useEffect(updateIsScrollable, [updateIsScrollable, width])
    useEffect(() => {
        const element = scrollRef.current
        if (element) {
            element.addEventListener('scroll', updateIsScrollable)
            return () => element.removeEventListener('scroll', updateIsScrollable)
        }
    }, [updateIsScrollable])

    /** Sorting. */
    const currentSorting =
        sorting ||
        (searchParams[currentSortingParam]
            ? searchParams[currentSortingParam].startsWith('-')
                ? {
                      columnKey: searchParams[currentSortingParam].substr(1),
                      order: -1,
                  }
                : {
                      columnKey: searchParams[currentSortingParam],
                      order: 1,
                  }
            : defaultSorting)
    /** Number of entries in total. */
    const entryCount: number | null = pagination?.controlled ? pagination.entryCount || null : dataSource.length
    /** Number of pages. */
    const pageCount: number | null =
        entryCount && (pagination ? (pagination.pageSize ? Math.ceil(entryCount / pagination.pageSize) : 1) : null)
    /** Page adjusted for `pageCount` possibly having gotten smaller since last page param update. */
    // Note: `pageCount` can logically only be null if pagination is controlled
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
            id={id}
            className={clsx(
                'LemonTable',
                size && size !== 'middle' && `LemonTable--${size}`,
                loading && 'LemonTable--loading',
                embedded && 'LemonTable--embedded',
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
                            {columns.map((column, index) => (
                                <col key={index} style={{ width: column.width }} />
                            ))}
                        </colgroup>
                        {showHeader && (
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
                                                          setLocalSorting(nextSorting)
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
                                                <div className="LemonTable__header-content">
                                                    {column.title}
                                                    {column.sorter && (
                                                        <SortingIndicator
                                                            order={
                                                                currentSorting?.columnKey ===
                                                                determineColumnKey(column, 'sorting')
                                                                    ? currentSorting.order
                                                                    : null
                                                            }
                                                        />
                                                    )}
                                                </div>
                                            </Tooltip>
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                        )}
                        <tbody>
                            {currentFrame.length ? (
                                currentFrame.map((record, rowIndex) => {
                                    const rowKeyDetermined = rowKey
                                        ? typeof rowKey === 'function'
                                            ? rowKey(record)
                                            : record[rowKey]
                                        : currentStartIndex + rowIndex
                                    const rowClassNameDetermined =
                                        typeof rowClassName === 'function' ? rowClassName(record) : rowClassName
                                    return (
                                        <TableRow
                                            key={`LemonTable-row-${rowKeyDetermined}`}
                                            record={record}
                                            recordIndex={currentStartIndex + rowIndex}
                                            rowKeyDetermined={rowKeyDetermined}
                                            rowClassNameDetermined={rowClassNameDetermined}
                                            columns={columns}
                                            onRow={onRow}
                                            expandable={expandable}
                                        />
                                    )
                                })
                            ) : (
                                <tr>
                                    <td colSpan={columns.length + Number(!!expandable)}>
                                        {emptyState || `No ${nouns[1]}`}
                                    </td>
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
