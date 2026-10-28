import type { ColumnDef, Row, SortingState } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconChevronRight, IconInfo } from '@posthog/icons'
import {
    Button,
    DataTable,
    Pagination,
    PaginationContent,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
    Skeleton,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { determineColumnKey } from './columnLayoutUtils'
import type { LemonTableProps } from './LemonTable'
import type { Sorting } from './sorting'
import type { LemonTableColumn, LemonTableColumnGroup, TableCellRenderResult, TableCellRepresentation } from './types'
import type { BulkSelectionKey } from './useBulkSelection'

const EXPAND_COLUMN_ID = '__expand'
const ROW_ACTIONS_COLUMN_ID = '__row_actions'

function isTableCellRepresentation(contents: TableCellRenderResult): contents is TableCellRepresentation {
    return !!contents && typeof contents === 'object' && !Array.isArray(contents) && !React.isValidElement(contents)
}

function toSortingState(sorting: Sorting | null): SortingState {
    return sorting ? [{ id: sorting.columnKey, desc: sorting.order === -1 }] : []
}

function fromSortingState(state: SortingState): Sorting | null {
    const [first] = state
    return first ? { columnKey: first.id, order: first.desc ? -1 : 1 } : null
}

function parseSortingParam(param: unknown): Sorting | null {
    if (typeof param !== 'string' || !param) {
        return null
    }
    return param.startsWith('-') ? { columnKey: param.slice(1), order: -1 } : { columnKey: param, order: 1 }
}

// Render callbacks receive the row's position on the current page, like LemonTable. The row model
// array is memoized by TanStack, so the position map is built once per row model, not once per cell.
const rowPositionCache = new WeakMap<Row<any>[], Map<string, number>>()
function getRowPosition<T>(rows: Row<T>[], row: Row<T>): number {
    let positions = rowPositionCache.get(rows)
    if (!positions) {
        positions = new Map(rows.map((r, index) => [r.id, index]))
        rowPositionCache.set(rows, positions)
    }
    return positions.get(row.id) ?? row.index
}

function ColumnTitle({ title, tooltip }: { title: React.ReactNode; tooltip?: string }): JSX.Element {
    if (!tooltip) {
        return <>{title}</>
    }
    return (
        <span className="inline-flex items-center gap-1">
            {title}
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent>{tooltip}</TooltipContent>
            </Tooltip>
        </span>
    )
}

/** Keeps the header pinned to the page only while the table fits its container. A wider table needs
 * its own scroll container to scroll sideways, and that container stops the header from pinning. */
function useTableFitsContainer(containerRef: React.RefObject<HTMLDivElement>): boolean {
    const [fits, setFits] = useState(true)
    useEffect(() => {
        const container = containerRef.current
        const table = container?.querySelector('table')
        if (!container || !table) {
            return
        }
        const update = (): void => setFits(table.offsetWidth <= container.clientWidth + 1)
        update()
        const observer = new ResizeObserver(update)
        observer.observe(container)
        observer.observe(table)
        return () => observer.disconnect()
    }, [containerRef])
    return fits
}

function ManualPager({
    currentPage = 1,
    pageSize,
    pageRowCount,
    entryCount,
    entryCountIsLowerBound,
    onForward,
    onBackward,
}: {
    currentPage?: number
    pageSize?: number
    pageRowCount: number
    entryCount?: number
    entryCountIsLowerBound?: boolean
    onForward?: () => void
    onBackward?: () => void
}): JSX.Element {
    const start = pageSize ? (currentPage - 1) * pageSize + 1 : null
    const end = start !== null ? start + pageRowCount - 1 : null
    return (
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-2">
            <span className="text-xs text-muted-foreground tabular-nums">
                {start !== null && end !== null && pageRowCount > 0
                    ? `${start}–${end}${entryCount != null ? ` of ${entryCount}${entryCountIsLowerBound ? '+' : ''}` : ''}`
                    : null}
            </span>
            <Pagination className="w-auto">
                <PaginationContent>
                    <PaginationItem>
                        <PaginationPrevious disabled={!onBackward} onClick={onBackward}>
                            <span className="sr-only">Previous</span>
                        </PaginationPrevious>
                    </PaginationItem>
                    <PaginationItem>
                        <PaginationNext disabled={!onForward} onClick={onForward}>
                            <span className="sr-only">Next</span>
                        </PaginationNext>
                    </PaginationItem>
                </PaginationContent>
            </Pagination>
        </div>
    )
}

/**
 * LemonTable's props rendered with the quill `DataTable`, for UI behind `today-rail-nav`.
 * Sorting keeps LemonTable's contract: `sorter` functions sort on the client, `sorter: true`
 * columns sort on the server, and `sorting`/`onSort`/`useURLForSorting` behave the same.
 */
export function QuillLemonTable<T extends Record<string, any>, K extends BulkSelectionKey = BulkSelectionKey>({
    id,
    columns: rawColumns,
    dataSource = [],
    rowKey,
    rowClassName,
    rowRibbonColor,
    rowStatus,
    onRow,
    size,
    loading,
    disableTableWhileLoading = true,
    pagination,
    expandable,
    noSortingCancellation = false,
    defaultSorting = null,
    sorting,
    onSort,
    useURLForSorting = true,
    loadingSkeletonRows = 1,
    emptyState,
    className,
    style,
    'data-attr': dataAttr,
    footer,
    allowContentScroll = false,
    rowActions,
}: LemonTableProps<T, K>): JSX.Element {
    const sortingParam = id ? `${id}_order` : 'order'
    const { location, searchParams, hashParams } = useValues(router)
    const { push } = useActions(router)
    const [internalSorting, setInternalSorting] = useState<Sorting | null>(sorting || null)

    const currentSorting: Sorting | null =
        sorting ||
        internalSorting ||
        (useURLForSorting ? parseSortingParam(searchParams[sortingParam]) : null) ||
        defaultSorting

    const columnGroups = useMemo(
        () =>
            (rawColumns.length > 0 && 'children' in rawColumns[0]
                ? rawColumns
                : [{ children: rawColumns }]) as LemonTableColumnGroup<T>[],
        [rawColumns]
    )
    const visibleColumns = useMemo(
        () => columnGroups.flatMap((group) => group.children).filter((column) => !column.isHidden),
        [columnGroups]
    )

    const sortedColumn = currentSorting
        ? visibleColumns.find((column) => determineColumnKey(column) === currentSorting.columnKey)
        : undefined
    // The server already ordered the rows for a `sorter: true` column.
    const manualSorting = sortedColumn?.sorter === true

    const handleSortingChange = useCallback(
        (next: SortingState) => {
            const nextSorting = fromSortingState(next)
            setInternalSorting(nextSorting)
            onSort?.(nextSorting)
            if (useURLForSorting) {
                push(
                    location.pathname,
                    {
                        ...searchParams,
                        [sortingParam]: nextSorting
                            ? `${nextSorting.order === -1 ? '-' : ''}${nextSorting.columnKey}`
                            : undefined,
                    },
                    hashParams
                )
            }
        },
        [location, searchParams, hashParams, push, useURLForSorting, onSort, sortingParam]
    )

    const recordIndex = useMemo(() => new Map(dataSource.map((record, index) => [record, index])), [dataSource])
    const getRowId = useCallback(
        (record: T, index: number): string => {
            if (typeof rowKey === 'function') {
                return String(rowKey(record, index))
            }
            if (rowKey !== undefined) {
                return String(record[rowKey])
            }
            return String(index)
        },
        [rowKey]
    )

    const [expandedState, setExpandedState] = useState<Record<string, boolean>>({})
    const expanded = useMemo(() => {
        if (!expandable?.isRowExpanded) {
            return expandedState
        }
        const merged = { ...expandedState }
        dataSource.forEach((record, index) => {
            const override = Number(expandable.isRowExpanded?.(record, index))
            if (override >= 0) {
                merged[getRowId(record, index)] = override > 0
            }
        })
        return merged
    }, [expandable, expandedState, dataSource, getRowId])
    const handleExpandedChange = useCallback(
        (next: Record<string, boolean>) => {
            dataSource.forEach((record, index) => {
                const rowId = getRowId(record, index)
                if (!!next[rowId] !== !!expanded[rowId]) {
                    ;(next[rowId] ? expandable?.onRowExpand : expandable?.onRowCollapse)?.(record, index)
                }
            })
            setExpandedState(next)
        },
        [dataSource, expanded, expandable, getRowId]
    )

    const columns = useMemo((): ColumnDef<T, unknown>[] => {
        const expandColumnId =
            visibleColumns.find((column) => column.fullWidth) ??
            visibleColumns.find((column) => column.width === undefined)
        const toColumnDef = (
            column: LemonTableColumn<T, keyof T | undefined>,
            index: number
        ): ColumnDef<T, unknown> => {
            const sorter = column.sorter
            return {
                id: determineColumnKey(column) ?? `column-${index}`,
                accessorFn: (record) => (column.dataIndex ? record[column.dataIndex] : undefined),
                header: () => <ColumnTitle title={column.title} tooltip={column.tooltip} />,
                cell: ({ row, table }) => {
                    const value = (column.dataIndex ? row.original[column.dataIndex] : undefined) as any
                    const contents = column.render
                        ? column.render(
                              value,
                              row.original,
                              getRowPosition(table.getRowModel().rows, row),
                              dataSource.length
                          )
                        : value
                    return isTableCellRepresentation(contents) ? contents.children : contents
                },
                enableSorting: !!sorter,
                sortingFn: typeof sorter === 'function' ? (a, b) => sorter(a.original, b.original) : undefined,
                sortDescFirst: column.defaultSortOrder === -1,
                meta: { align: column.align, expand: column === expandColumnId },
            }
        }

        let leafIndex = 0
        const hasGroupTitles = columnGroups.some((group) => group.title)
        const dataColumns: ColumnDef<T, unknown>[] = hasGroupTitles
            ? columnGroups.map((group, groupIndex) => ({
                  id: `group-${groupIndex}`,
                  header: () => group.title,
                  columns: group.children
                      .filter((column) => !column.isHidden)
                      .map((column) => toColumnDef(column, leafIndex++)),
              }))
            : visibleColumns.map((column) => toColumnDef(column, leafIndex++))

        const expandColumn: ColumnDef<T, unknown>[] =
            expandable && expandable.showRowExpansionToggle !== false
                ? [
                      {
                          id: EXPAND_COLUMN_ID,
                          header: () => null,
                          enableSorting: false,
                          cell: ({ row }) =>
                              row.getCanExpand() ? (
                                  <Button
                                      size="icon-sm"
                                      aria-label={row.getIsExpanded() ? 'Collapse row' : 'Expand row'}
                                      aria-expanded={row.getIsExpanded()}
                                      onClick={row.getToggleExpandedHandler()}
                                  >
                                      <IconChevronRight
                                          className={cn('transition-transform', row.getIsExpanded() && 'rotate-90')}
                                      />
                                  </Button>
                              ) : null,
                      },
                  ]
                : []
        const rowActionsColumn: ColumnDef<T, unknown>[] = rowActions
            ? [
                  {
                      id: ROW_ACTIONS_COLUMN_ID,
                      header: () => null,
                      enableSorting: false,
                      meta: { align: 'right' },
                      cell: ({ row, table }) => rowActions(row.original, getRowPosition(table.getRowModel().rows, row)),
                  },
              ]
            : []
        return [...expandColumn, ...dataColumns, ...rowActionsColumn]
    }, [columnGroups, visibleColumns, expandable, rowActions, dataSource.length])

    const getRowProps = useCallback(
        (record: T, index: number): React.ComponentProps<'tr'> => {
            const rowProps = (onRow?.(record, index) ?? {}) as React.ComponentProps<'tr'>
            const status = typeof rowStatus === 'function' ? rowStatus(record, index) : rowStatus
            const ribbonColor = typeof rowRibbonColor === 'function' ? rowRibbonColor(record, index) : rowRibbonColor
            return {
                ...rowProps,
                className: cn(
                    rowProps.className,
                    typeof rowClassName === 'function' ? rowClassName(record, index) : rowClassName,
                    status && 'bg-fill-selected'
                ),
                style: ribbonColor ? { ...rowProps.style, boxShadow: `inset 3px 0 0 ${ribbonColor}` } : rowProps.style,
            }
        },
        [onRow, rowStatus, rowRibbonColor, rowClassName]
    )

    const autoPageSize =
        pagination &&
        !pagination.controlled &&
        !(pagination.hideOnSinglePage !== false && dataSource.length <= pagination.pageSize)
            ? pagination.pageSize
            : undefined
    const showManualPager =
        !!pagination?.controlled &&
        (pagination.hideOnSinglePage === false || !!pagination.onForward || !!pagination.onBackward)

    const containerRef = useRef<HTMLDivElement>(null)
    const tableFitsContainer = useTableFitsContainer(containerRef)

    const showSkeleton = loading && dataSource.length === 0
    const empty = showSkeleton ? (
        <div className="flex flex-col gap-2" aria-busy>
            {Array.from({ length: loadingSkeletonRows }, (_, index) => (
                <Skeleton key={index} className="h-4 w-full" />
            ))}
        </div>
    ) : (
        emptyState
    )

    return (
        <div
            ref={containerRef}
            data-quill
            data-attr={dataAttr}
            aria-busy={loading || undefined}
            className={cn(
                'flex flex-col gap-2 [--quill-table-sticky-top:var(--lemon-table-sticky-header-top,0px)]',
                loading && !showSkeleton && disableTableWhileLoading && 'pointer-events-none opacity-60',
                className
            )}
            style={style}
        >
            <DataTable<T, unknown>
                columns={columns}
                data={dataSource}
                size={size === 'small' ? 'sm' : 'default'}
                fullWidth
                stickyHeader={allowContentScroll ? true : tableFitsContainer ? 'page' : false}
                empty={empty}
                pageSize={autoPageSize}
                sorting={toSortingState(currentSorting)}
                onSortingChange={handleSortingChange}
                manualSorting={manualSorting}
                enableSortingRemoval={!noSortingCancellation}
                getRowId={getRowId}
                getRowProps={getRowProps}
                renderExpandedRow={
                    expandable
                        ? (record) => expandable.expandedRowRender(record, recordIndex.get(record) ?? 0)
                        : undefined
                }
                getRowCanExpand={
                    expandable?.rowExpandable
                        ? (record) => Number(expandable.rowExpandable?.(record, recordIndex.get(record) ?? 0)) > 0
                        : undefined
                }
                expanded={expanded}
                onExpandedChange={handleExpandedChange}
            />
            {showManualPager && pagination?.controlled ? (
                <ManualPager
                    currentPage={pagination.currentPage}
                    pageSize={pagination.pageSize}
                    pageRowCount={dataSource.length}
                    entryCount={pagination.entryCount}
                    entryCountIsLowerBound={pagination.entryCountIsLowerBound}
                    onForward={pagination.onForward}
                    onBackward={pagination.onBackward}
                />
            ) : null}
            {footer}
        </div>
    )
}
