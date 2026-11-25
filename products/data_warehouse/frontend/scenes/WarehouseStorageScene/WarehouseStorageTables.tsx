import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconPlay } from '@posthog/icons'
import { Button, DataTable, type DataTableProps, Input, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { formatBytes, formatCount } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { type StorageTableRow, tablePreviewUrl, warehouseStorageLogic } from './warehouseStorageLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const numeric = (content: React.ReactNode): JSX.Element => (
    <span className="whitespace-nowrap tabular-nums">{content}</span>
)

// Declared at module level so TanStack keeps the cell identities across renders.
const COLUMNS: DataTableProps<StorageTableRow, unknown>['columns'] = [
    {
        accessorKey: 'qualified_name',
        header: 'Table',
        meta: { expand: true },
        cell: ({ row }) => (
            <span className="block max-w-80 truncate font-mono text-xs" title={row.original.qualified_name}>
                <span className="text-muted-foreground">{row.original.schema}.</span>
                {row.original.table}
            </span>
        ),
    },
    {
        accessorKey: 'size_bytes',
        header: 'Size',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ row }) => numeric(formatBytes(row.original.size_bytes)),
    },
    {
        accessorKey: 'row_count',
        header: 'Rows',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ row }) => numeric(formatCount(row.original.row_count)),
    },
    {
        accessorKey: 'file_count',
        header: 'Files',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ row }) => numeric(formatCount(row.original.file_count)),
    },
    {
        accessorKey: 'last_modified_at',
        header: 'Last changed',
        meta: { align: 'right' },
        cell: ({ row }) => <WarehouseTime iso={row.original.last_modified_at} />,
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
                <IconPlay />
                Query
            </Button>
        ),
    },
]

export function WarehouseStorageTables(): JSX.Element {
    const { filteredTableRows, tableRows, search } = useValues(warehouseStorageLogic)
    const { setSearch } = useActions(warehouseStorageLogic)

    return (
        <WarehouseSection
            title="Tables"
            flush
            data-attr="warehouse-storage-tables"
            controls={
                <Input
                    className="w-56 max-w-full"
                    placeholder="Search tables"
                    aria-label="Search tables"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    data-attr="warehouse-storage-search"
                />
            }
        >
            <DataTable
                columns={COLUMNS}
                data={filteredTableRows}
                size="sm"
                fullWidth
                pageSize={25}
                empty={
                    <Text size="sm" variant="muted" className="px-3 py-4">
                        {tableRows.length === 0
                            ? 'Tables appear here once data is written to your warehouse.'
                            : 'No tables match your search.'}
                    </Text>
                }
            />
        </WarehouseSection>
    )
}
