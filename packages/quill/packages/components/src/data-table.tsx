import {
    type ColumnDef,
    type PaginationState,
    type RowData,
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
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

// Per-column extras read off `columnDef.meta`. `align` drives intra-cell
// alignment on both the header and its body cells; `expand` makes the column
// soak up leftover width in a `fullWidth` table.
declare module '@tanstack/react-table' {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- generics are fixed by TanStack's declaration
    interface ColumnMeta<TData extends RowData, TValue> {
        align?: 'left' | 'center' | 'right'
        expand?: boolean
    }
}

export interface DataTableProps<TData, TValue> {
    columns: ColumnDef<TData, TValue>[]
    data: TData[]
    /** Sizing/scroll classes for the table container (forwarded to the Table primitive). */
    className?: string
    /** Sticky header mode, forwarded to the Table primitive. `'page'` sticks to document scroll. */
    stickyHeader?: boolean | 'page'
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
}: {
    table: TanstackTable<TData>
    pageSizeOptions?: number[]
}): React.ReactElement {
    const { pageIndex, pageSize } = table.getState().pagination
    const pageCount = table.getPageCount()
    const total = table.getFilteredRowModel().rows.length
    const start = total === 0 ? 0 : pageIndex * pageSize + 1
    const end = Math.min((pageIndex + 1) * pageSize, total)
    const range = getPaginationRange(pageCount, pageIndex)

    // px-3 matches the cells' 0.75rem inline padding so the pager lines up under
    // the column content.
    return (
        <div className="flex flex-wrap items-center justify-between gap-2 px-3">
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
                        <PaginationPrevious disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}>
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
                                    onClick={() => table.setPageIndex(item)}
                                >
                                    {item + 1}
                                </PaginationButton>
                            </PaginationItem>
                        )
                    )}
                    <PaginationItem>
                        <PaginationNext disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}>
                            <span className="sr-only">Next</span>
                        </PaginationNext>
                    </PaginationItem>
                </PaginationContent>
            </Pagination>
        </div>
    )
}

/**
 * Headless TanStack Table wired onto the quill Table primitive — client-side
 * sorting out of the box (sortable columns render a sort button + indicator and
 * set `aria-sort`), selection reflected via the row's `data-state`, optional
 * pagination, and an empty state. Pass `enableSorting: false` on a column to opt
 * it out, `meta: { align }` to align a column's header and cells, or
 * `fullWidth` + `meta: { expand: true }` to stretch one column to fill.
 */
function DataTable<TData, TValue>({
    columns,
    data,
    className,
    stickyHeader,
    fullWidth,
    size,
    empty = DEFAULT_EMPTY,
    pageSize,
    pageSizeOptions,
}: DataTableProps<TData, TValue>): React.ReactElement {
    const paginated = pageSize != null
    const [sorting, setSorting] = React.useState<SortingState>([])
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
        columns,
        state: { sorting, ...(paginated ? { pagination } : {}) },
        onSortingChange: setSorting,
        ...(paginated ? { onPaginationChange: setPagination } : {}),
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
        ...(paginated ? { getPaginationRowModel: getPaginationRowModel() } : {}),
    })
    const rows = table.getRowModel().rows

    const tableElement = (
        <Table className={className} stickyHeader={stickyHeader} fullWidth={fullWidth} size={size}>
            <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                    <TableRow key={headerGroup.id}>
                        {headerGroup.headers.map((header) => {
                            const sorted = header.column.getIsSorted()
                            const { align, expand } = header.column.columnDef.meta ?? {}
                            const label = header.isPlaceholder
                                ? null
                                : flexRender(header.column.columnDef.header, header.getContext())
                            return (
                                <TableHead
                                    key={header.id}
                                    colSpan={header.colSpan}
                                    align={align}
                                    expand={expand}
                                    aria-sort={sorted ? ARIA_SORT[sorted] : undefined}
                                >
                                    {header.column.getCanSort() && !header.isPlaceholder ? (
                                        <Button
                                            size="sm"
                                            // The Button's built-in selected styling (fill-selected, with
                                            // hover preserved via its own :not(:hover) rule) marks the
                                            // active sort. Real semantics live in aria-sort on the <th>.
                                            aria-selected={sorted ? true : undefined}
                                            className={cn(
                                                'gap-1.5',
                                                sorted && 'text-foreground',
                                                !sorted && 'hover:bg-fill-hover/50'
                                            )}
                                            onClick={header.column.getToggleSortingHandler()}
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
                                </TableHead>
                            )
                        })}
                    </TableRow>
                ))}
            </TableHeader>
            <TableBody>
                {rows.length ? (
                    rows.map((row) => (
                        <TableRow key={row.id} data-state={row.getIsSelected() ? 'selected' : undefined}>
                            {row.getVisibleCells().map((cell) => (
                                <TableCell
                                    key={cell.id}
                                    align={cell.column.columnDef.meta?.align}
                                    expand={cell.column.columnDef.meta?.expand}
                                >
                                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                </TableCell>
                            ))}
                        </TableRow>
                    ))
                ) : (
                    <TableRow>
                        <TableCell colSpan={columns.length} className="p-2 hover:bg-transparent">
                            {empty}
                        </TableCell>
                    </TableRow>
                )}
            </TableBody>
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
            <DataTablePagination table={table} pageSizeOptions={pageSizeOptions} />
        </div>
    )
}

export { DataTable }
