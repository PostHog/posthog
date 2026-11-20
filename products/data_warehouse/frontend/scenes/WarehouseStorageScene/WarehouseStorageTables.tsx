import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    DataTable,
    type DataTableProps,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Input,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { formatBytes } from '../WarehouseConsole/warehouseConsoleFormat'
import { type StorageTableRow, tablePreviewUrl, warehouseStorageLogic } from './warehouseStorageLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

// Declared at module level so TanStack keeps the cell identities across renders.
const COLUMNS: DataTableProps<StorageTableRow, unknown>['columns'] = [
    {
        accessorKey: 'qualified_name',
        header: 'Table',
        meta: { expand: true },
        cell: ({ row }) => (
            <span className="block max-w-80 truncate font-mono text-xs" title={row.original.qualified_name}>
                {row.original.qualified_name}
            </span>
        ),
    },
    {
        accessorKey: 'size_bytes',
        header: 'Size',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ row }) => <span className="whitespace-nowrap">{formatBytes(row.original.size_bytes)}</span>,
    },
    {
        accessorKey: 'row_count',
        header: 'Rows',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ row }) => humanFriendlyNumber(row.original.row_count),
    },
    {
        accessorKey: 'file_count',
        header: 'Files',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ row }) => humanFriendlyNumber(row.original.file_count),
    },
    {
        accessorKey: 'last_modified_at',
        header: 'Last changed',
        meta: { align: 'right' },
        cell: ({ row }) =>
            row.original.last_modified_at ? (
                <TZLabel time={row.original.last_modified_at} timestampStyle="relative" />
            ) : (
                '-'
            ),
    },
    {
        id: 'actions',
        header: '',
        enableSorting: false,
        meta: { align: 'right', sticky: 'right' },
        cell: ({ row }) => (
            <Button
                size="sm"
                nativeButton={false}
                render={<LinkPrimitive to={tablePreviewUrl(row.original.schema, row.original.table)} />}
                onClick={() => posthog.capture('warehouse storage table query clicked')}
                data-attr="warehouse-storage-table-query"
            >
                Query
            </Button>
        ),
    },
]

export function WarehouseStorageTables(): JSX.Element {
    const { filteredTableRows, tableRows, search } = useValues(warehouseStorageLogic)
    const { setSearch } = useActions(warehouseStorageLogic)

    return (
        <Card data-attr="warehouse-storage-tables">
            <CardHeader>
                <CardTitle>Tables</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                <Input
                    className="max-w-sm"
                    placeholder="Search tables"
                    aria-label="Search tables"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    data-attr="warehouse-storage-search"
                />
                <DataTable
                    columns={COLUMNS}
                    data={filteredTableRows}
                    size="sm"
                    fullWidth
                    pageSize={25}
                    empty={
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>{tableRows.length === 0 ? 'No tables yet' : 'No tables match'}</EmptyTitle>
                                <EmptyDescription>
                                    {tableRows.length === 0
                                        ? 'Tables appear here once data is written to your warehouse.'
                                        : 'Try a different search.'}
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    }
                />
            </CardContent>
        </Card>
    )
}
