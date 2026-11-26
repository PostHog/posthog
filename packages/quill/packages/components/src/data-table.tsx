import {
    type ColumnDef,
    type ColumnSizingState,
    type PaginationState,
    type RowSelectionState,
    type Row,
    type RowData,
    type Header,
    type OnChangeFn,
    type SortingState,
    type Table as TanstackTable,
    flexRender,
    getCoreRowModel,
    getPaginationRowModel,
    getSortedRowModel,
    useReactTable,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ChevronsUpDown, Inbox } from 'lucide-react'
import * as React from 'react'

import {
    Button,
    Checkbox,
    cn,
    Empty,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    getPaginationRange,
    Pagination,
    PaginationButton,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
    MIN_TABLE_COLUMN_WIDTH,
    Table,
    TableBody,
    TableCell,
    TableColumnResizer,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { useColumnWidths } from './use-column-widths'

// Per-column extras read off `columnDef.meta`. `align` drives intra-cell
// alignment on both the header and its body cells; `expand` makes the column
// soak up leftover width in a `fullWidth` table.
declare module '@tanstack/react-table' {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- generics are fixed by TanStack's declaration
    interface ColumnMeta<TData extends RowData, TValue> {
        align?: 'left' | 'center' | 'right'
        expand?: boolean
        sticky?: 'left' | 'right'
        /** `data-attr` for the column's sort button. */
        sortDataAttr?: string
    }
}

const ROW_CLICK_IGNORE_SELECTOR = [
    'a',
    'button',
    'input',
    'select',
    'textarea',
    'label',
    'summary',
    'audio[controls]',
    'video[controls]',
    '[contenteditable]:not([contenteditable="false"])',
    '[tabindex]:not([tabindex="-1"])',
    '[role="button"]',
    '[role="checkbox"]',
    '[role="combobox"]',
    '[role="link"]',
    '[role="listbox"]',
    '[role="menuitem"]',
    '[role="menuitemcheckbox"]',
    '[role="menuitemradio"]',
    '[role="option"]',
    '[role="radio"]',
    '[role="searchbox"]',
    '[role="slider"]',
    '[role="spinbutton"]',
    '[role="switch"]',
    '[role="tab"]',
    '[role="textbox"]',
    '[role="treeitem"]',
    '[data-row-click-ignore]',
].join(', ')

function shouldIgnoreRowClick(target: EventTarget | null, row: HTMLTableRowElement): boolean {
    if (!(target instanceof Element)) {
        return false
    }

    const interactiveElement = target.closest(ROW_CLICK_IGNORE_SELECTOR)

    return interactiveElement !== null && interactiveElement !== row
}

export interface DataTableProps<TData, TValue> {
    columns: ColumnDef<TData, TValue>[]
    data: TData[]
    /** Opens or selects a record when the user clicks a non-interactive part of its row. */
    onRowClick?: (row: TData) => void
    /** Optional class name for a row, for example to highlight a selected record. */
    rowClassName?: (row: TData) => string | undefined
    /** Called when the user moves between pages. Page numbers are one-based. */
    onPageChange?: (page: number, nextPage: number) => void
    /** Sizing/scroll classes for the table container (forwarded to the Table primitive). */
    className?: string
    /** Sticky header mode, forwarded to the Table primitive. `'page'` sticks to document scroll. */
    stickyHeader?: boolean | 'page'
    /** Ref to the scrolling viewport, forwarded to the Table primitive. */
    viewportRef?: React.Ref<HTMLDivElement>
    /** Ref to a marker after the table, inside the viewport. Observe it to load more rows near the end. */
    viewportEndRef?: React.Ref<HTMLDivElement>
    /**
     * Controls the sort. The rows then stay in the order of `data`, so the caller must sort them, for example on the
     * server. Without this prop, the table sorts its rows on the client.
     */
    sorting?: SortingState
    /** Called with the next sort when the user clicks a sortable header. */
    onSortingChange?: (sorting: SortingState) => void
    /**
     * Lets the user drag the edge of a column to resize it, with the arrow keys as well. Columns fit their content until
     * the first resize. Use `minSize` and `maxSize` on a column to bound it, and `enableResizing: false` to opt it out.
     */
    resizableColumns?: boolean
    /** Controls the widths of the resized columns, in pixels by column id. Pass a saved value to restore them. */
    columnSizing?: ColumnSizingState
    /** Called with the next widths when a resize ends. A double click on an edge removes that column's width. */
    onColumnSizingChange?: (columnSizing: ColumnSizingState) => void
    /**
     * Stretch the table to fill its container (forwarded to the Table primitive).
     * Mark a column with `meta: { expand: true }` to choose which one absorbs the
     * slack.
     */
    fullWidth?: boolean
    /**
     * Cell density, forwarded to the Table primitive. `'sm'` tightens head/cell
     * inline padding to `0.75rem` — pair with a `Card size="sm"` so edge columns
     * align with the card's inline padding.
     */
    size?: 'default' | 'sm'
    /**
     * Rendered in place of rows when `data` is empty. Defaults to a minimal
     * "No results" Empty; pass a richer node (custom copy, actions) to override.
     */
    empty?: React.ReactNode
    /**
     * Adds a leading checkbox column so the user can select rows. Shift-click a checkbox to set every row between it
     * and the last one clicked. The header checkbox selects or clears every selectable row on the page.
     */
    selectable?: boolean
    /** Controls the selection, as `true` by row id. Pass `getRowId` so that a selection survives a change of `data`. */
    rowSelection?: RowSelectionState
    onRowSelectionChange?: (rowSelection: RowSelectionState) => void
    /** The id of a row, for `rowSelection`. Defaults to the row's index in `data`. */
    getRowId?: (row: TData, index: number) => string
    /** The accessible name of a row's checkbox. Defaults to "Select row". */
    rowSelectionLabel?: (row: TData) => string
    /**
     * Why a row can't be selected. A reason disables the row's checkbox and shows in its tooltip, and `null` lets the
     * user select the row. A shift-click range skips the disabled rows.
     */
    rowSelectionDisabledReason?: (row: TData) => string | null
    /**
     * Enables client-side pagination at this page size and renders a pager below
     * the table. Omit for a single, un-paginated list.
     */
    pageSize?: number
    /**
     * Page-size choices shown in a selector beside the pager. Only rendered when
     * `pageSize` is set; omit to hide the selector and keep a fixed page size.
     */
    pageSizeOptions?: number[]
}

// `getIsSorted()` → ARIA sort token for the header cell.
const ARIA_SORT = { asc: 'ascending', desc: 'descending' } as const

// Minimal, generic empty state. Deliberately unopinionated — no app-specific
// copy or action buttons; pass a richer `empty` for those. Module-level so it's
// not re-created each render and stays out of the function signature.
const DEFAULT_EMPTY = (
    <Empty>
        <EmptyHeader>
            <EmptyMedia variant="icon">
                <Inbox />
            </EmptyMedia>
            <EmptyTitle>No results</EmptyTitle>
        </EmptyHeader>
    </Empty>
)

// Pager rendered below the table: a row range summary, an optional page-size
// selector, and first/last + sibling-window page buttons with ellipses.
function DataTablePagination<TData>({
    table,
    pageSizeOptions,
    onPageChange,
}: {
    table: TanstackTable<TData>
    pageSizeOptions?: number[]
    onPageChange?: (page: number, nextPage: number) => void
}): React.ReactElement {
    const { pageIndex, pageSize } = table.getState().pagination
    const pageCount = table.getPageCount()
    const total = table.getFilteredRowModel().rows.length
    const start = total === 0 ? 0 : pageIndex * pageSize + 1
    const end = Math.min((pageIndex + 1) * pageSize, total)
    const range = getPaginationRange(pageCount, pageIndex)
    const goToPage = (nextPageIndex: number): void => {
        onPageChange?.(pageIndex + 1, nextPageIndex + 1)
        table.setPageIndex(nextPageIndex)
    }

    // px-3 matches the cells' 0.75rem inline padding. Bottom padding keeps the
    // controls clear of a flush card's edge.
    return (
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="tabular-nums">
                    {start}–{end} of {total}
                </span>
                {pageSizeOptions?.length ? (
                    <Select value={String(pageSize)} onValueChange={(value) => table.setPageSize(Number(value))}>
                        <SelectTrigger size="sm" className="w-auto gap-1" aria-label="Rows per page">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                {pageSizeOptions.map((size) => (
                                    <SelectItem key={size} value={String(size)}>
                                        {size} / page
                                    </SelectItem>
                                ))}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                ) : null}
            </div>
            <Pagination className="w-auto">
                <PaginationContent>
                    <PaginationItem>
                        <PaginationPrevious
                            disabled={!table.getCanPreviousPage()}
                            onClick={() => goToPage(pageIndex - 1)}
                        >
                            <span className="sr-only">Previous</span>
                        </PaginationPrevious>
                    </PaginationItem>
                    {range.map((item, i) =>
                        item === 'ellipsis' ? (
                            <PaginationItem key={`ellipsis-${i}`}>
                                <PaginationEllipsis />
                            </PaginationItem>
                        ) : (
                            <PaginationItem key={item}>
                                <PaginationButton
                                    isActive={item === pageIndex}
                                    aria-label={`Go to page ${item + 1}`}
                                    onClick={() => goToPage(item)}
                                >
                                    {item + 1}
                                </PaginationButton>
                            </PaginationItem>
                        )
                    )}
                    <PaginationItem>
                        <PaginationNext disabled={!table.getCanNextPage()} onClick={() => goToPage(pageIndex + 1)}>
                            <span className="sr-only">Next</span>
                        </PaginationNext>
                    </PaginationItem>
                </PaginationContent>
            </Pagination>
        </div>
    )
}

// State a caller may control: its value wins when given, and either way the caller hears about each change.
function useControllable<T>(
    controlled: T | undefined,
    onChange: ((next: T) => void) | undefined,
    initial: T
): [T, OnChangeFn<T>] {
    const [internal, setInternal] = React.useState<T>(initial)
    const value = controlled ?? internal
    return [
        value,
        (updater) => {
            const next = typeof updater === 'function' ? (updater as (old: T) => T)(value) : updater
            setInternal(next)
            onChange?.(next)
        },
    ]
}

function DataTableHead<TData>({
    header,
    resizable,
    width,
    onResizeStart,
}: {
    header: Header<TData, unknown>
    resizable: boolean
    width: number | undefined
    onResizeStart: () => void
}): React.ReactElement {
    const { column, isPlaceholder } = header
    const sorted = column.getIsSorted()
    const { align, expand, sticky, sortDataAttr } = column.columnDef.meta ?? {}
    const label = isPlaceholder ? null : flexRender(column.columnDef.header, header.getContext())
    const title = column.columnDef.header
    return (
        <TableHead
            colSpan={header.colSpan}
            align={align}
            expand={expand}
            sticky={sticky}
            aria-sort={sorted ? ARIA_SORT[sorted] : undefined}
            // While the columns fit their content, this is what holds an expand column at its minimum.
            style={expand && resizable ? { minWidth: column.columnDef.minSize } : undefined}
        >
            {column.getCanSort() && !isPlaceholder ? (
                <Button
                    size="sm"
                    // The Button's built-in selected styling (fill-selected, with
                    // hover preserved via its own :not(:hover) rule) marks the
                    // active sort. Real semantics live in aria-sort on the <th>.
                    aria-selected={sorted ? true : undefined}
                    data-attr={sortDataAttr}
                    className={cn('gap-1.5', sorted && 'text-foreground', !sorted && 'hover:bg-fill-hover/50')}
                    onClick={column.getToggleSortingHandler()}
                >
                    {label}
                    {sorted === 'asc' ? (
                        <ArrowUp className="size-3" />
                    ) : sorted === 'desc' ? (
                        <ArrowDown className="size-3" />
                    ) : (
                        <ChevronsUpDown className="size-3 opacity-50" />
                    )}
                </Button>
            ) : (
                label
            )}
            {resizable ? (
                <TableColumnResizer
                    value={width}
                    min={column.columnDef.minSize}
                    max={column.columnDef.maxSize}
                    aria-label={typeof title === 'string' ? `Resize ${title} column` : undefined}
                    onResizeStart={onResizeStart}
                    onValueCommitted={(next) =>
                        header.getContext().table.setColumnSizing((sizes) => ({ ...sizes, [column.id]: next }))
                    }
                    onReset={() => column.resetSize()}
                />
            ) : null}
        </TableHead>
    )
}

// Memoized so that a resize, which ends by setting a width on the table, does not render every row again. For the same
// reason, a caller with its own state should keep `columns`, `onRowClick`, `rowClassName` and `empty` stable between renders.
// TanStack keeps `rows` the same array when only the selection changes, so `rowSelection` and `rowSelectionDisabledReason`
// are props that the body never reads: they are there to make the memo render the rows again.
function DataTableBodyInner<TData, TValue>({
    rows,
    columns,
    filler,
    onRowClick,
    rowClassName,
    empty,
}: {
    rows: Row<TData>[]
    rowSelection: RowSelectionState
    rowSelectionDisabledReason: DataTableProps<TData, TValue>['rowSelectionDisabledReason']
    columns: ColumnDef<TData, TValue>[]
    filler: boolean
    onRowClick?: (row: TData) => void
    rowClassName?: (row: TData) => string | undefined
    empty: React.ReactNode
}): React.ReactElement {
    return (
        <TableBody>
            {rows.length ? (
                rows.map((row) => (
                    <TableRow
                        key={row.id}
                        data-state={row.getIsSelected() ? 'selected' : undefined}
                        className={cn(
                            onRowClick &&
                                'cursor-pointer focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring',
                            rowClassName?.(row.original)
                        )}
                        tabIndex={onRowClick ? 0 : undefined}
                        onClick={
                            onRowClick
                                ? (event) => {
                                      if (!shouldIgnoreRowClick(event.target, event.currentTarget)) {
                                          onRowClick(row.original)
                                      }
                                  }
                                : undefined
                        }
                        onKeyDown={
                            onRowClick
                                ? (event) => {
                                      if (
                                          event.target === event.currentTarget &&
                                          (event.key === 'Enter' || event.key === ' ')
                                      ) {
                                          event.preventDefault()
                                          onRowClick(row.original)
                                      }
                                  }
                                : undefined
                        }
                    >
                        {row.getVisibleCells().map((cell) => (
                            <TableCell
                                key={cell.id}
                                align={cell.column.columnDef.meta?.align}
                                expand={cell.column.columnDef.meta?.expand}
                                sticky={cell.column.columnDef.meta?.sticky}
                            >
                                {flexRender(cell.column.columnDef.cell, cell.getContext())}
                            </TableCell>
                        ))}
                        {filler ? <TableCell filler /> : null}
                    </TableRow>
                ))
            ) : (
                <TableRow>
                    <TableCell colSpan={columns.length + (filler ? 1 : 0)} className="p-2 hover:bg-transparent">
                        {empty}
                    </TableCell>
                </TableRow>
            )}
        </TableBody>
    )
}

const DataTableBody = React.memo(DataTableBodyInner) as typeof DataTableBodyInner

const SELECTION_COLUMN_ID = '__select'

function isShiftClick(event: Event | undefined): boolean {
    return (event instanceof MouseEvent || event instanceof KeyboardEvent) && event.shiftKey
}

// Shift-click would otherwise select the page's text between the two checkboxes.
function preventShiftTextSelection(event: React.MouseEvent): void {
    if (event.shiftKey) {
        event.preventDefault()
    }
}

function selectRange<TData>(
    current: RowSelectionState,
    rows: Row<TData>[],
    fromId: string,
    toId: string,
    checked: boolean
): RowSelectionState {
    const from = rows.findIndex((row) => row.id === fromId)
    const to = rows.findIndex((row) => row.id === toId)
    const next = { ...current }
    for (const row of rows.slice(Math.min(from, to), Math.max(from, to) + 1)) {
        if (!row.getCanSelect()) {
            continue
        }
        if (checked) {
            next[row.id] = true
        } else {
            delete next[row.id]
        }
    }
    return next
}

function useSelectionColumn<TData>(
    selectable: boolean,
    rowSelectionLabel: ((row: TData) => string) | undefined,
    rowSelectionDisabledReason: ((row: TData) => string | null) | undefined
): ColumnDef<TData, unknown> | null {
    const anchorRowId = React.useRef<string | null>(null)
    // Read through refs so that inline callbacks keep the column, and with it the memoized body, the same between renders.
    const labelRef = React.useRef(rowSelectionLabel)
    labelRef.current = rowSelectionLabel
    const disabledReasonRef = React.useRef(rowSelectionDisabledReason)
    disabledReasonRef.current = rowSelectionDisabledReason
    return React.useMemo(() => {
        if (!selectable) {
            return null
        }
        return {
            id: SELECTION_COLUMN_ID,
            enableSorting: false,
            enableResizing: false,
            header: ({ table }) => (
                <Checkbox
                    aria-label="Select all rows"
                    checked={table.getIsAllPageRowsSelected()}
                    indeterminate={table.getIsSomePageRowsSelected()}
                    disabled={!table.getRowModel().rows.some((row) => row.getCanSelect())}
                    onCheckedChange={(checked) => {
                        anchorRowId.current = null
                        table.toggleAllPageRowsSelected(checked)
                    }}
                />
            ),
            cell: ({ row, table }) => (
                <Checkbox
                    aria-label={labelRef.current?.(row.original) ?? 'Select row'}
                    checked={row.getIsSelected()}
                    disabled={!row.getCanSelect()}
                    disabledReason={disabledReasonRef.current?.(row.original)}
                    onMouseDown={preventShiftTextSelection}
                    onCheckedChange={(checked, details) => {
                        const anchorId = anchorRowId.current
                        anchorRowId.current = row.id
                        const rows = table.getRowModel().rows
                        if (
                            anchorId !== null &&
                            isShiftClick(details.event) &&
                            rows.some((candidate) => candidate.id === anchorId)
                        ) {
                            table.setRowSelection((current) => selectRange(current, rows, anchorId, row.id, checked))
                        } else {
                            row.toggleSelected(checked)
                        }
                    }}
                />
            ),
        }
    }, [selectable])
}

/**
 * Headless TanStack Table wired onto the quill Table primitive — client-side
 * sorting out of the box (sortable columns render a sort button + indicator and
 * set `aria-sort`), selection reflected via the row's `data-state`, optional
 * pagination, and an empty state. Pass `enableSorting: false` on a column to opt
 * it out, `meta: { align }` to align a column's header and cells,
 * `fullWidth` + `meta: { expand: true }` to stretch one column to fill, or
 * `resizableColumns` to let the user drag a column's edge, or `selectable` to add a checkbox column for selecting rows.
 */
function DataTable<TData, TValue>({
    columns,
    data,
    onRowClick,
    rowClassName,
    className,
    stickyHeader,
    viewportRef,
    viewportEndRef,
    sorting: controlledSorting,
    onSortingChange,
    resizableColumns = false,
    columnSizing: controlledColumnSizing,
    onColumnSizingChange,
    fullWidth = false,
    size,
    empty = DEFAULT_EMPTY,
    pageSize,
    pageSizeOptions,
    onPageChange,
    selectable = false,
    rowSelection: controlledRowSelection,
    onRowSelectionChange,
    getRowId,
    rowSelectionLabel,
    rowSelectionDisabledReason,
}: DataTableProps<TData, TValue>): React.ReactElement {
    const paginated = pageSize != null
    const [rowSelection, setRowSelection] = useControllable<RowSelectionState>(
        controlledRowSelection,
        onRowSelectionChange,
        {}
    )
    const selectionColumn = useSelectionColumn<TData>(selectable, rowSelectionLabel, rowSelectionDisabledReason)
    const tableColumns = React.useMemo(
        () => (selectionColumn ? [selectionColumn as ColumnDef<TData, TValue>, ...columns] : columns),
        [selectionColumn, columns]
    )
    const [sorting, setSorting] = useControllable<SortingState>(controlledSorting, onSortingChange, [])
    const [columnSizing, setColumnSizing] = useControllable<ColumnSizingState>(
        controlledColumnSizing,
        onColumnSizingChange,
        {}
    )
    const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: pageSize ?? 10 })
    // Keep the page size in sync when the prop changes at runtime — reset to the
    // first page so the new size applies from a consistent offset.
    React.useEffect(() => {
        if (pageSize != null) {
            setPagination((prev) => ({ ...prev, pageIndex: 0, pageSize }))
        }
    }, [pageSize])
    const table = useReactTable({
        data,
        columns: tableColumns,
        getRowId,
        // TanStack merges each render's options into the last ones, so a removed callback must reset to its default.
        enableRowSelection: rowSelectionDisabledReason
            ? (row: Row<TData>) => rowSelectionDisabledReason(row.original) === null
            : true,
        onRowSelectionChange: setRowSelection,
        enableColumnResizing: resizableColumns,
        defaultColumn: { minSize: MIN_TABLE_COLUMN_WIDTH, maxSize: Infinity },
        state: { sorting, columnSizing, rowSelection, ...(paginated ? { pagination } : {}) },
        onColumnSizingChange: setColumnSizing,
        manualSorting: controlledSorting !== undefined,
        // A list sorted on the server always has an order, so its headers have no "off" state.
        enableSortingRemoval: controlledSorting === undefined,
        onSortingChange: setSorting,
        ...(paginated ? { onPaginationChange: setPagination } : {}),
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
        ...(paginated ? { getPaginationRowModel: getPaginationRowModel() } : {}),
    })
    const tableRef = React.useRef<HTMLTableElement>(null)
    const { columnWidths, columnWidth, fixColumnWidths } = useColumnWidths(table, tableRef, resizableColumns)
    // A resize changes the dragged column and no other, so once widths are fixed no column absorbs the difference, not
    // even an `expand` one. In a full-width table an empty column fills whatever space the others leave.
    const hasFiller = resizableColumns && fullWidth
    const headerGroups = table.getHeaderGroups()

    const tableElement = (
        <Table
            ref={tableRef}
            columnWidths={columnWidths}
            className={className}
            stickyHeader={stickyHeader}
            viewportRef={viewportRef}
            viewportEndRef={viewportEndRef}
            fullWidth={fullWidth}
            size={size}
        >
            <TableHeader>
                {headerGroups.map((headerGroup, index) => (
                    <TableRow key={headerGroup.id}>
                        {headerGroup.headers.map((header) => (
                            <DataTableHead
                                key={header.id}
                                header={header}
                                // Only the last row of headers lines up one to one with the columns.
                                resizable={index === headerGroups.length - 1 && header.column.getCanResize()}
                                width={columnWidth(header.column.id)}
                                onResizeStart={fixColumnWidths}
                            />
                        ))}
                        {hasFiller ? <TableHead filler /> : null}
                    </TableRow>
                ))}
            </TableHeader>
            <DataTableBody
                rows={table.getRowModel().rows}
                rowSelection={table.getState().rowSelection}
                rowSelectionDisabledReason={rowSelectionDisabledReason}
                columns={tableColumns}
                filler={hasFiller}
                onRowClick={onRowClick}
                rowClassName={rowClassName}
                empty={empty}
            />
        </Table>
    )

    // Nothing to paginate when the table is empty — the empty state already
    // signals the absence of data, so a "0–0 of 0" pager is just noise.
    if (!paginated || table.getFilteredRowModel().rows.length === 0) {
        return tableElement
    }

    return (
        <div className="flex flex-col gap-2">
            {tableElement}
            <DataTablePagination table={table} pageSizeOptions={pageSizeOptions} onPageChange={onPageChange} />
        </div>
    )
}

export { DataTable }
