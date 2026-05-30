import {
    type ColumnDef,
    type SortingState,
    flexRender,
    getCoreRowModel,
    getSortedRowModel,
    useReactTable,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import * as React from 'react'

import { Button, cn, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill-primitives'

export interface DataTableProps<TData, TValue> {
    columns: ColumnDef<TData, TValue>[]
    data: TData[]
    /** Sizing/scroll classes for the table container (forwarded to the Table primitive). */
    className?: string
    /** Sticky header mode, forwarded to the Table primitive. `'page'` sticks to document scroll. */
    stickyHeader?: boolean | 'page'
    /** Shown in place of rows when `data` is empty. */
    emptyMessage?: React.ReactNode
}

// `getIsSorted()` → ARIA sort token for the header cell.
const ARIA_SORT = { asc: 'ascending', desc: 'descending' } as const

/**
 * Headless TanStack Table wired onto the quill Table primitive — client-side
 * sorting out of the box (sortable columns render a sort button + indicator and
 * set `aria-sort`), selection reflected via the row's `data-state`, and an empty
 * state. Pass `enableSorting: false` on a column to opt it out.
 */
function DataTable<TData, TValue>({
    columns,
    data,
    className,
    stickyHeader,
    emptyMessage = 'No results.',
}: DataTableProps<TData, TValue>): React.ReactElement {
    const [sorting, setSorting] = React.useState<SortingState>([])
    const table = useReactTable({
        data,
        columns,
        state: { sorting },
        onSortingChange: setSorting,
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
    })
    const rows = table.getRowModel().rows

    return (
        <Table className={className} stickyHeader={stickyHeader}>
            <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                    <TableRow key={headerGroup.id}>
                        {headerGroup.headers.map((header) => {
                            const sorted = header.column.getIsSorted()
                            const label = header.isPlaceholder
                                ? null
                                : flexRender(header.column.columnDef.header, header.getContext())
                            return (
                                <TableHead
                                    key={header.id}
                                    colSpan={header.colSpan}
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
                                                "gap-1.5",
                                                sorted && 'text-foreground',
                                                !sorted && 'hover:bg-fill-hover/50',
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
                                <TableCell key={cell.id}>
                                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                </TableCell>
                            ))}
                        </TableRow>
                    ))
                ) : (
                    <TableRow>
                        <TableCell
                            colSpan={columns.length}
                            className="py-6 text-center text-[var(--muted-foreground)]"
                        >
                            {emptyMessage}
                        </TableCell>
                    </TableRow>
                )}
            </TableBody>
        </Table>
    )
}

export { DataTable }
