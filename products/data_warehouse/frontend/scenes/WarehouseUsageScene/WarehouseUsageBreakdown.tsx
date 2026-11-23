import { useActions, useValues } from 'kea'

import { DataTable, type DataTableProps, Text } from '@posthog/quill'

import { formatBytes, formatCount, formatPercent, formatUsd } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { type SegmentedOption, WarehouseSegmentedControl } from '../WarehouseConsole/WarehouseSegmentedControl'
import { WarehouseShareBar } from '../WarehouseConsole/WarehouseShareBar'
import { type BreakdownRow, type UsageGroupBy, warehouseUsageLogic } from './warehouseUsageLogic'

const GROUP_BY_OPTIONS: SegmentedOption<UsageGroupBy>[] = [
    { value: 'source', label: 'Source', 'data-attr': 'warehouse-usage-group-by-source' },
    { value: 'principal', label: 'Login', 'data-attr': 'warehouse-usage-group-by-principal' },
    { value: 'team', label: 'Project', 'data-attr': 'warehouse-usage-group-by-team' },
]

// Declared at module level so TanStack keeps the cell identities across renders.
const COLUMNS: DataTableProps<BreakdownRow, unknown>['columns'] = [
    {
        accessorKey: 'label',
        header: 'Name',
        meta: { expand: true },
        cell: ({ row }) => (
            <span className="block max-w-72 truncate" title={row.original.label}>
                {row.original.label}
            </span>
        ),
    },
    {
        accessorKey: 'queries',
        header: 'Queries',
        meta: { align: 'right' },
        cell: ({ row }) => <span className="tabular-nums">{formatCount(row.original.queries)}</span>,
    },
    {
        accessorKey: 'billable_bytes',
        header: 'Scanned',
        meta: { align: 'right' },
        cell: ({ row }) => (
            <span className="whitespace-nowrap tabular-nums">{formatBytes(row.original.billable_bytes)}</span>
        ),
    },
    {
        accessorKey: 'estimated_cost_share_usd',
        header: 'Est. cost',
        meta: { align: 'right' },
        cell: ({ row }) => (
            <span className="whitespace-nowrap tabular-nums">{formatUsd(row.original.estimated_cost_share_usd)}</span>
        ),
    },
    {
        accessorKey: 'shareOfBytes',
        header: 'Share',
        meta: { align: 'right' },
        cell: ({ row }) => (
            <div className="flex items-center justify-end gap-2">
                <WarehouseShareBar fraction={row.original.shareOfBytes} label="Share of scanned data" />
                <span className="w-10 text-right tabular-nums">{formatPercent(row.original.shareOfBytes)}</span>
            </div>
        ),
    },
]

export function WarehouseUsageBreakdown(): JSX.Element | null {
    const { usage, breakdownRows, groupBy, usageLoading } = useValues(warehouseUsageLogic)
    const { setGroupBy } = useActions(warehouseUsageLogic)

    if (!usage) {
        return null
    }

    return (
        <WarehouseSection
            title="Spend breakdown"
            flush
            data-attr="warehouse-usage-breakdown"
            controls={
                <WarehouseSegmentedControl
                    value={groupBy}
                    options={GROUP_BY_OPTIONS}
                    onChange={setGroupBy}
                    label="Group spend by"
                    disabled={usageLoading}
                />
            }
        >
            <DataTable
                columns={COLUMNS}
                data={breakdownRows}
                size="sm"
                fullWidth
                empty={
                    <Text size="sm" variant="muted" className="px-3 py-4">
                        No queries in this period.
                    </Text>
                }
            />
        </WarehouseSection>
    )
}
