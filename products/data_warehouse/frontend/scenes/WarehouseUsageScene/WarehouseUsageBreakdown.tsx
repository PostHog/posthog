import { useActions, useValues } from 'kea'

import {
    DataTable,
    type DataTableProps,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Progress,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { formatBytes, formatPercent, formatUsd } from '../WarehouseConsole/warehouseConsoleFormat'
import { type BreakdownRow, type UsageGroupBy, warehouseUsageLogic } from './warehouseUsageLogic'

const GROUP_BY_OPTIONS: { value: UsageGroupBy; label: string }[] = [
    { value: 'source', label: 'Source' },
    { value: 'principal', label: 'Login' },
    { value: 'team', label: 'Project' },
]

// Declared at module level so TanStack keeps the cell identities across renders.
const COLUMNS: DataTableProps<BreakdownRow, unknown>['columns'] = [
    {
        accessorKey: 'label',
        header: 'Name',
        meta: { expand: true },
        cell: ({ row }) => <span className="block max-w-72 truncate">{row.original.label}</span>,
    },
    { accessorKey: 'queries', header: 'Queries', meta: { align: 'right' } },
    {
        accessorKey: 'billable_bytes',
        header: 'Billable scanned',
        meta: { align: 'right' },
        cell: ({ row }) => formatBytes(row.original.billable_bytes),
    },
    {
        accessorKey: 'estimated_cost_share_usd',
        header: 'Est. cost',
        meta: { align: 'right' },
        cell: ({ row }) => formatUsd(row.original.estimated_cost_share_usd),
    },
    {
        accessorKey: 'shareOfBytes',
        header: 'Share',
        meta: { align: 'right' },
        cell: ({ row }) => (
            <div className="flex items-center justify-end gap-2">
                <Progress value={row.original.shareOfBytes * 100} className="w-16" aria-label="Share of scanned data" />
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
        <Card data-attr="warehouse-usage-breakdown">
            <CardHeader className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle>Spend breakdown</CardTitle>
                <ToggleGroup
                    variant="outline"
                    size="sm"
                    value={[groupBy]}
                    onValueChange={(value) => {
                        const next = value[0] as UsageGroupBy | undefined
                        if (next && next !== groupBy) {
                            setGroupBy(next)
                        }
                    }}
                    aria-label="Group spend by"
                >
                    {GROUP_BY_OPTIONS.map((option) => (
                        <ToggleGroupItem
                            key={option.value}
                            value={option.value}
                            disabled={usageLoading}
                            data-attr={`warehouse-usage-group-by-${option.value}`}
                        >
                            {option.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </CardHeader>
            <CardContent>
                <DataTable
                    columns={COLUMNS}
                    data={breakdownRows}
                    size="sm"
                    fullWidth
                    empty={
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>No queries in this period</EmptyTitle>
                                <EmptyDescription>Spend appears here once queries run.</EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    }
                />
            </CardContent>
        </Card>
    )
}
