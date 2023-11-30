import './LemonTable.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useScrollable } from 'lib/hooks/useScrollable'
import { IconInfo } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import React, { HTMLProps, useCallback, useEffect, useMemo, useState } from 'react'

import { PaginationAuto, PaginationControl, PaginationManual, usePagination } from '../PaginationControl'
import { Tooltip } from '../Tooltip'
import { LemonTableLoader } from './LemonTableLoader'
import { getNextSorting, Sorting, SortingIndicator } from './sorting'
import { TableRow } from './TableRow'
import { ExpandableConfig, LemonTableColumn, LemonTableColumnGroup, LemonTableColumns } from './types'

/**
 * Determine the column's key, using `dataIndex` as fallback.
 * If `obligationReason` is specified, will throw an error if the key can't be determined.
 */
function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason: string): string
function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason?: undefined): string | null
function determineColumnKey(column: LemonTableColumn<any, any>, obligationReason?: string): string | null {
    const columnKey = column.key || column.dataIndex
    if (obligationReason && columnKey == null) {
        // == is intentional to catch undefined too
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
    rowKey?: keyof T | ((record: T, rowIndex: number) => string | number)
    /** Class to append to each row. */
    rowClassName?: string | ((record: T, rowIndex: number) => string | null)
    /** Color to mark each row with. */
    rowRibbonColor?: string | ((record: T, rowIndex: number) => string | null)
    /** Status of each row. Defaults no status. */
    rowStatus?: 'highlighted' | ((record: T, rowIndex: number) => 'highlighted' | null)
    /** Function that for each row determines what props should its `tr` element have based on the row's record. */
    onRow?: (record: T) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    /** How tall should rows be. The default value is `"middle"`. */
    size?: 'xs' | 'small' | 'middle'
    /** Whether this table already is inset, meaning it needs reduced horizontal padding (0.5rem instead of 1rem). */
    inset?: boolean
    /** An embedded table has no border around it and no background. This way it blends better into other components. */
    embedded?: boolean
    /** Whether inner table borders should be shown. **/
    borderedRows?: boolean
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
    noSortingCancellation?: boolean
    /** Sorting order to start with. */
    defaultSorting?: Sorting | null
    /** Controlled sort order. */
    sorting?: Sorting | null
    /** Sorting change handler for controlled sort order. */
    onSort?: (newSorting: Sorting | null) => void
    /** Defaults to true. Used if you don't want to use the URL to store sort order **/
    useURLForSorting?: boolean
    /** How many skeleton rows should be used for the empty loading state. The default value is 1. */
    loadingSkeletonRows?: number
    /** What to show when there's no data. */
    emptyState?: React.ReactNode
    /** What to describe the entries as, singular and plural. The default value is `['entry', 'entries']`. */
    nouns?: [string, string]
    className?: string
    style?: React.CSSProperties
    'data-attr'?: string
    display?: 'stealth' | 'default'
    /** Footer to be shown below the table. */
    footer?: React.ReactNode
    /** Whether the first column should always remain visible when scrolling horizontally. */
    firstColumnSticky?: boolean
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
    inset = false,
    embedded = false,
    borderedRows = true,
    loading,
    pagination,
    expandable,
    showHeader = true,
    uppercaseHeader = true,
    noSortingCancellation: disableSortingCancellation = false,
    defaultSorting = null,
    sorting,
    onSort,
    useURLForSorting = true,
    loadingSkeletonRows = 1,
    emptyState,
    nouns = ['entry', 'entries'],
    className,
    style,
    'data-attr': dataAttr,
    display = 'default',
    footer,
    firstColumnSticky,
}: LemonTableProps<T>): JSX.Element {
    /** Search param that will be used for storing and syncing sorting */
    const currentSortingParam = id ? `${id}_order` : 'order'

    const { location, searchParams, hashParams } = useValues(router)
    const { push } = useActions(router)

    // used when not using URL to store sorting
    const [internalSorting, setInternalSorting] = useState<Sorting | null>(sorting || null)

    /** update sorting and conditionally replace the current browsing history item */
    const setLocalSorting = useCallback(
        (newSorting: Sorting | null) => {
            setInternalSorting(newSorting)
            onSort?.(newSorting)
            if (useURLForSorting) {
                return push(
                    location.pathname,
                    {
                        ...searchParams,
                        [currentSortingParam]: newSorting
                            ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                            : undefined,
                    },
                    hashParams
                )
            }
        },
        [location, searchParams, hashParams, push]
    )

    const columnGroups = (
        rawColumns.length > 0 && 'children' in rawColumns[0]
            ? rawColumns
            : [
                  {
                      children: rawColumns,
                  },
              ]
    ) as LemonTableColumnGroup<T>[]
    const columns = columnGroups.flatMap((group) => group.children)

    const [scrollRef, [isScrollableLeft, isScrollableRight]] = useScrollable()

    /** Sorting. */
    const currentSorting =
        sorting ||
        internalSorting ||
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

    if (firstColumnSticky && expandable) {
        // Due to CSS, for firstColumnSticky to work the first column needs to be a content column
        throw new Error('LemonTable `firstColumnSticky` prop cannot be used with `expandable`')
    }

    return (
        <div
            id={id}
            className={clsx(
                'LemonTable scrollable',
                size && size !== 'middle' && `LemonTable--${size}`,
                inset && 'LemonTable--inset',
                loading && 'LemonTable--loading',
                embedded && 'LemonTable--embedded',
                rowRibbonColor !== undefined && `LemonTable--with-ribbon`,
                !borderedRows && 'LemonTable--borderless-rows',
                display === 'stealth' && 'LemonTable--stealth',
                isScrollableLeft && 'scrollable--left',
                isScrollableRight && 'scrollable--right',
                className
            )}
            style={style}
            data-attr={dataAttr}
        >
            <div className="scrollable__inner" ref={scrollRef}>
                <div className="LemonTable__content">
                    <table>
                        <colgroup>
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
                                        {!!expandable && <th className="LemonTable__toggle" /> /* Expand/collapse */}
                                        {columnGroups.map((columnGroup, columnGroupIndex) =>
                                            columnGroupIndex === 0 && firstColumnSticky ? (
                                                <React.Fragment key={`LemonTable-th-group-${columnGroupIndex}`}>
                                                    <th
                                                        colSpan={1}
                                                        className="LemonTable__boundary LemonTable__header--sticky"
                                                    >
                                                        {columnGroup.title}
                                                    </th>
                                                    <th colSpan={columnGroup.children.length - 1} />
                                                </React.Fragment>
                                            ) : (
                                                <th
                                                    key={`LemonTable-th-group-${columnGroupIndex}`}
                                                    colSpan={columnGroup.children.length}
                                                    className="LemonTable__boundary"
                                                >
                                                    {columnGroup.title}
                                                </th>
                                            )
                                        )}
                                    </tr>
                                )}
                                <tr>
                                    {!!expandable && <th className="LemonTable__toggle" /> /* Expand/collapse */}
                                    {columnGroups.flatMap((columnGroup, columnGroupIndex) =>
                                        columnGroup.children.map((column, columnIndex) => (
                                            <th
                                                key={`LemonTable-th-${columnGroupIndex}-${
                                                    determineColumnKey(column) ?? columnIndex
                                                }`}
                                                className={clsx(
                                                    'LemonTable__header',
                                                    column.sorter && 'LemonTable__header--actionable',
                                                    columnIndex === 0 && 'LemonTable__boundary',
                                                    firstColumnSticky &&
                                                        columnGroupIndex === 0 &&
                                                        columnIndex === 0 &&
                                                        'LemonTable__header--sticky',
                                                    column.className
                                                )}
                                                /* eslint-disable-next-line react/forbid-dom-props */
                                                style={{ textAlign: column.align }}
                                                onClick={
                                                    column.sorter && !column.more
                                                        ? () => {
                                                              const nextSorting = getNextSorting(
                                                                  currentSorting,
                                                                  determineColumnKey(column, 'sorting'),
                                                                  disableSortingCancellation
                                                              )

                                                              setLocalSorting(nextSorting)
                                                          }
                                                        : undefined
                                                }
                                            >
                                                <div
                                                    className="LemonTable__header-content"
                                                    /* eslint-disable-next-line react/forbid-dom-props */
                                                    style={{ justifyContent: column.align }}
                                                >
                                                    <div className="flex items-center">
                                                        {column.tooltip ? (
                                                            <Tooltip title={column.tooltip}>
                                                                <div className="flex items-center">
                                                                    {column.title}
                                                                    <IconInfo className="ml-1 text-base" />
                                                                </div>
                                                            </Tooltip>
                                                        ) : (
                                                            column.title
                                                        )}
                                                        {column.sorter && (
                                                            <Tooltip
                                                                title={() => {
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
                                                                }}
                                                            >
                                                                <SortingIndicator
                                                                    order={
                                                                        currentSorting?.columnKey ===
                                                                        determineColumnKey(column, 'sorting')
                                                                            ? currentSorting.order
                                                                            : null
                                                                    }
                                                                />
                                                                {/* this non-breaking space lets antd's tooltip work*/}{' '}
                                                            </Tooltip>
                                                        )}
                                                    </div>
                                                    {column.more && (
                                                        <More
                                                            overlay={column.more}
                                                            className="ml-1"
                                                            data-attr="table-header-more"
                                                        />
                                                    )}
                                                </div>
                                            </th>
                                        ))
                                    )}
                                    <LemonTableLoader loading={loading} tag="th" />
                                </tr>
                            </thead>
                        )}
                        <tbody>
                            {paginationState.dataSourcePage.length ? (
                                paginationState.dataSourcePage.map((record, rowIndex) => {
                                    const rowKeyDetermined = rowKey
                                        ? typeof rowKey === 'function'
                                            ? rowKey(record, rowIndex)
                                            : record[rowKey] ?? rowIndex
                                        : paginationState.currentStartIndex + rowIndex
                                    const rowClassNameDetermined =
                                        typeof rowClassName === 'function'
                                            ? rowClassName(record, rowIndex)
                                            : rowClassName
                                    const rowRibbonColorDetermined =
                                        typeof rowRibbonColor === 'function'
                                            ? rowRibbonColor(record, rowIndex) || 'var(--border-light)'
                                            : rowRibbonColor
                                    const rowStatusDetermined =
                                        typeof rowStatus === 'function' ? rowStatus(record, rowIndex) : rowStatus
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
                                            firstColumnSticky={firstColumnSticky}
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
                                                            firstColumnSticky &&
                                                                columnIndex === 0 &&
                                                                'LemonTable__cell--sticky',
                                                            column.className
                                                        )}
                                                    >
                                                        <LemonSkeleton />
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
                    {footer && <div className="LemonTable__footer">{footer}</div>}

                    <PaginationControl {...paginationState} nouns={nouns} />
                    <div className="LemonTable__overlay" />
                </div>
            </div>
        </div>
    )
}
