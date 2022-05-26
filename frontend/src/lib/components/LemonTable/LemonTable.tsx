import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { HTMLProps, useCallback, useEffect, useMemo } from 'react'
import { Tooltip } from '../Tooltip'
import { TableRow } from './TableRow'
import './LemonTable.scss'
import { Sorting, SortingIndicator, getNextSorting } from './sorting'
import { ExpandableConfig, LemonTableColumn, LemonTableColumnGroup, LemonTableColumns } from './types'
import { PaginationAuto, PaginationControl, PaginationManual, usePagination } from '../PaginationControl'
import { Skeleton } from 'antd'
import { useScrollable } from 'lib/hooks/useScrollable'

/**
 * Determine the column's key, using `dataIndex` as fallback.
 * If `obligationReason` is specified, will throw an error if the key can't be determined.
 */
function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason: string): string
function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason?: undefined): string | null
function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason?: string): string | null {
    const columnKey = column.key || column.dataIndex
    if (obligationReason && !columnKey) {
        throw new Error(`Column \`key\` or \`dataIndex\` must be defined for ${obligationReason}`)
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
    /** Class to append to each row. */
    rowClassName?: string | ((record: T) => string | null)
    /** Color to mark each row with. */
    rowRibbonColor?: string | ((record: T) => string | null)
    /** Status of each row. Defaults no status. */
    rowStatus?: 'highlighted' | ((record: T) => 'highlighted' | null)
    /** Function that for each row determines what props should its `tr` element have based on the row's record. */
    onRow?: (record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    /** How tall should rows be. The default value is `"middle"`. */
    size?: 'small' | 'middle'
    /** An embedded table has no border around it and no background. This way it blends better into other components. */
    embedded?: boolean
    loading?: boolean
    pagination?: PaginationAuto | PaginationManual
    expandable?: ExpandableConfig<T>
    /** Whether the header should be shown. The default value is `true`. */
    showHeader?: boolean
    /** Whether header titles should be uppercased. The default value is `true`. */
    uppercaseHeader?: boolean
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
    /** How many skeleton rows should be used for the empty loading state. The default value is 1. */
    loadingSkeletonRows?: number
    /** What to show when there's no data. */
    emptyState?: React.ReactNode
    /** What to describe the entries as, singular and plural. The default value is `['entry', 'entries']`. */
    nouns?: [string, string]
    className?: string
    style?: React.CSSProperties
    'data-attr'?: string
}

export function LemonTable<T extends Record<string, any>>({
    id,
    columns: rawColumns,
    dataSource = [],
    rowKey,
    rowClassName,
    rowRibbonColor,
    rowStatus,
    onRow,
    size,
    embedded = false,
    loading,
    pagination,
    expandable,
    showHeader = true,
    uppercaseHeader = true,
    disableSortingCancellation = false,
    defaultSorting = null,
    sorting,
    onSort,
    loadingSkeletonRows = 1,
    emptyState,
    nouns = ['entry', 'entries'],
    className,
    style,
    'data-attr': dataAttr,
}: LemonTableProps<T>): JSX.Element {
    /** Search param that will be used for storing and syncing sorting */
    const currentSortingParam = id ? `${id}_order` : 'order'

    const { location, searchParams, hashParams } = useValues(router)
    const { push } = useActions(router)

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

    const columnGroups = (
        'children' in rawColumns[0]
            ? rawColumns
            : [
                  {
                      children: rawColumns,
                  },
              ]
    ) as LemonTableColumnGroup<T>[]
    const columns = columnGroups.flatMap((group) => group.children)

    const [scrollRef, scrollableClassNames] = useScrollable()

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

    const sortedDataSource = useMemo(() => {
        if (currentSorting) {
            const { columnKey: sortColumnKey, order: sortOrder } = currentSorting
            const sorter = columns.find(
                (searchColumn) => searchColumn.sorter && determineColumnKey(searchColumn, 'sorting') === sortColumnKey
            )?.sorter
            if (typeof sorter === 'function') {
                return dataSource.slice().sort((a, b) => sortOrder * sorter(a, b))
            }
        }
        return dataSource
    }, [dataSource, currentSorting])

    const paginationState = usePagination(sortedDataSource, pagination, id)

    useEffect(() => {
        // When the current page changes, scroll back to the top of the table
        if (scrollRef.current) {
            const realTableOffsetTop = scrollRef.current.getBoundingClientRect().top - 320 // Extra breathing room
            // If the table starts above the top edge of the view, scroll to the top of the table minus breathing room
            if (realTableOffsetTop < 0) {
                window.scrollTo(window.scrollX, window.scrollY + realTableOffsetTop)
            }
        }
    }, [paginationState.currentPage, scrollRef.current])

    return (
        <div
            id={id}
            className={clsx(
                'LemonTable',
                size && size !== 'middle' && `LemonTable--${size}`,
                loading && 'LemonTable--loading',
                embedded && 'LemonTable--embedded',
                ...scrollableClassNames,
                className
            )}
            style={style}
            data-attr={dataAttr}
        >
            <div className="scrollable__inner" ref={scrollRef}>
                <div className="LemonTable__content">
                    <table>
                        <colgroup>
                            {!!rowRibbonColor && <col style={{ width: 4 }} /> /* Ribbon column */}
                            {!!expandable && <col style={{ width: 0 }} /> /* Expand/collapse column */}
                            {columns.map((column, index) => (
                                <col key={`LemonTable-col-${index}`} style={{ width: column.width }} />
                            ))}
                        </colgroup>
                        {showHeader && (
                            <thead
                                style={
                                    !uppercaseHeader ? { textTransform: 'none', letterSpacing: 'normal' } : undefined
                                }
                            >
                                {columnGroups.some((group) => group.title) && (
                                    <tr className="LemonTable__row--grouping">
                                        {!!rowRibbonColor && <th className="LemonTable__ribbon" /> /* Ribbon column */}
                                        {!!expandable && <th /> /* Expand/collapse column */}
                                        {columnGroups.map((columnGroup, columnGroupIndex) => (
                                            <th
                                                key={`LemonTable-th-group-${columnGroupIndex}`}
                                                colSpan={columnGroup.children.length}
                                                className="LemonTable__boundary"
                                            >
                                                {columnGroup.title}
                                            </th>
                                        ))}
                                    </tr>
                                )}
                                <tr>
                                    {!!rowRibbonColor && <th className="LemonTable__ribbon" /> /* Ribbon column */}
                                    {!!expandable && <th /> /* Expand/collapse column */}
                                    {columnGroups.flatMap((columnGroup, columnGroupIndex) =>
                                        columnGroup.children.map((column, columnIndex) => (
                                            <th
                                                key={`LemonTable-th-${columnGroupIndex}-${
                                                    determineColumnKey(column) || columnIndex
                                                }`}
                                                className={clsx(
                                                    column.sorter && 'LemonTable__header--actionable',
                                                    columnIndex === columnGroup.children.length - 1 &&
                                                        'LemonTable__boundary',
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
                                                    <div
                                                        className="LemonTable__header-content"
                                                        style={{ justifyContent: column.align }}
                                                    >
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
                                        ))
                                    )}
                                </tr>
                                <tr className="LemonTable__loader" />
                            </thead>
                        )}
                        <tbody>
                            {paginationState.dataSourcePage.length ? (
                                paginationState.dataSourcePage.map((record, rowIndex) => {
                                    const rowKeyDetermined = rowKey
                                        ? typeof rowKey === 'function'
                                            ? rowKey(record)
                                            : record[rowKey] ?? rowIndex
                                        : paginationState.currentStartIndex + rowIndex
                                    const rowClassNameDetermined =
                                        typeof rowClassName === 'function' ? rowClassName(record) : rowClassName
                                    const rowRibbonColorDetermined =
                                        typeof rowRibbonColor === 'function'
                                            ? rowRibbonColor(record) || 'var(--border-light)'
                                            : rowRibbonColor
                                    const rowStatusDetermined =
                                        typeof rowStatus === 'function' ? rowStatus(record) : rowStatus
                                    return (
                                        <TableRow
                                            key={`LemonTable-tr-${rowKeyDetermined}`}
                                            record={record}
                                            recordIndex={paginationState.currentStartIndex + rowIndex}
                                            rowKeyDetermined={rowKeyDetermined}
                                            rowClassNameDetermined={rowClassNameDetermined}
                                            rowRibbonColorDetermined={rowRibbonColorDetermined}
                                            rowStatusDetermined={rowStatusDetermined}
                                            columnGroups={columnGroups}
                                            onRow={onRow}
                                            expandable={expandable}
                                        />
                                    )
                                })
                            ) : loading ? (
                                Array(loadingSkeletonRows)
                                    .fill(null)
                                    .map((_, rowIndex) => (
                                        <tr key={`LemonTable-tr-${rowIndex} ph-no-capture`}>
                                            {columnGroups.flatMap((columnGroup, columnGroupIndex) =>
                                                columnGroup.children.map((column, columnIndex) => (
                                                    <td
                                                        key={`LemonTable-td-${columnGroupIndex}-${columnIndex}`}
                                                        className={clsx(
                                                            columnIndex === columnGroup.children.length - 1 &&
                                                                'LemonTable__boundary',
                                                            column.className
                                                        )}
                                                    >
                                                        <Skeleton title paragraph={false} active />
                                                    </td>
                                                ))
                                            )}
                                        </tr>
                                    ))
                            ) : (
                                <tr className="LemonTable__empty-state">
                                    <td colSpan={columns.length + Number(!!expandable)}>
                                        {emptyState || `No ${nouns[1]}`}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                    <PaginationControl {...paginationState} nouns={nouns} />
                    <div className="LemonTable__overlay" />
                </div>
            </div>
        </div>
    )
}
