import { useActions, useValues } from 'kea'

import {
    DataTable,
    type DataTableProps,
    Badge,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { QueryHistoryRowApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { duration } from '../DataOpsScene/tabs/trinoMonitoringFormat'
import { formatBytes, formatUsd } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseFilterSelect } from './WarehouseFilterSelect'
import { type HistoryRangeFilter, type HistoryStatusFilter, warehouseQueriesLogic } from './warehouseQueriesLogic'
import { WarehouseSqlBlock } from './WarehouseSqlBlock'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const STATUS_OPTIONS: { value: HistoryStatusFilter; label: string }[] = [
    { value: 'all', label: 'All statuses' },
    { value: 'FINISHED', label: 'Finished' },
    { value: 'FAILED', label: 'Failed' },
]

const RANGE_OPTIONS: { value: HistoryRangeFilter; label: string }[] = [
    { value: '24h', label: 'Last 24 hours' },
    { value: '7d', label: 'Last 7 days' },
    { value: '30d', label: 'Last 30 days' },
]

function errorSummary(row: QueryHistoryRowApi): string | null {
    const parts = [row.error_type, row.error_code].filter(Boolean)
    return parts.length > 0 ? parts.join(' / ') : null
}

function QueryCell({ row }: { row: QueryHistoryRowApi }): JSX.Element {
    const { expandedRowIds } = useValues(warehouseQueriesLogic)
    const expanded = expandedRowIds.includes(row.id)
    const error = errorSummary(row)

    const hiddenNote = "SQL hidden: you don't have access to this project"
    if (!expanded) {
        return row.query === null ? (
            <Text size="xs" variant="muted">
                SQL hidden
            </Text>
        ) : (
            <code className="block max-w-96 truncate font-mono text-xs" title="Click the row to see the full query">
                {row.query}
            </code>
        )
    }
    return (
        <div className="flex min-w-0 max-w-[40rem] flex-col gap-2 py-1" data-row-click-ignore>
            {row.query === null ? (
                <Text size="xs" variant="muted">
                    {hiddenNote}
                </Text>
            ) : (
                <WarehouseSqlBlock sql={row.query} />
            )}
            {row.state === 'FAILED' ? (
                <Text size="xs" variant="destructive">
                    {error ? `Failed with ${error}.` : 'Failed.'}
                </Text>
            ) : null}
            <Text size="xs" variant="muted">
                Query id <code className="font-mono">{row.query_id}</code>
            </Text>
        </div>
    )
}

// Declared at module level so TanStack keeps the cell identities across renders.
const COLUMNS: DataTableProps<QueryHistoryRowApi, unknown>['columns'] = [
    {
        id: 'created_at',
        header: 'Time',
        enableSorting: false,
        cell: ({ row }) =>
            row.original.created_at ? <TZLabel time={row.original.created_at} timestampStyle="relative" /> : '-',
    },
    {
        id: 'query',
        header: 'Query',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => <QueryCell row={row.original} />,
    },
    { accessorKey: 'principal_label', header: 'Login', enableSorting: false },
    { accessorKey: 'source_label', header: 'Source', enableSorting: false },
    {
        id: 'state',
        header: 'Status',
        enableSorting: false,
        cell: ({ row }) => {
            const failed = row.original.state === 'FAILED'
            const error = errorSummary(row.original)
            return (
                <div className="flex flex-col items-start gap-0.5">
                    <Badge variant={failed ? 'destructive' : 'success'}>{failed ? 'Failed' : 'Finished'}</Badge>
                    {failed && error ? (
                        <Text size="xs" variant="muted">
                            {error}
                        </Text>
                    ) : null}
                </div>
            )
        },
    },
    {
        id: 'elapsed_ms',
        header: 'Duration',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (row.original.elapsed_ms == null ? '-' : duration(row.original.elapsed_ms)),
    },
    {
        id: 'queued_ms',
        header: 'Queued',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (row.original.queued_ms == null ? '-' : duration(row.original.queued_ms)),
    },
    {
        id: 'billable_bytes',
        header: 'Billable scanned',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => formatBytes(row.original.billable_bytes),
    },
    {
        id: 'estimated_cost_usd',
        header: 'Est. cost',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (row.original.billable ? formatUsd(row.original.estimated_cost_usd) : 'Not billed'),
    },
]

export function WarehouseQueryHistory(): JSX.Element {
    const {
        history,
        historyLoading,
        historyFailed,
        loadMoreFailed,
        historyRows,
        hasMoreHistory,
        statusFilter,
        sourceFilter,
        principalFilter,
        rangeFilter,
        sourceOptions,
        principalOptions,
    } = useValues(warehouseQueriesLogic)
    const {
        setStatusFilter,
        setSourceFilter,
        setPrincipalFilter,
        setRangeFilter,
        toggleHistoryRow,
        loadMoreHistory,
        retryHistory,
    } = useActions(warehouseQueriesLogic)

    let body: JSX.Element
    if (historyFailed) {
        body = (
            <WarehouseResourceError
                title="Couldn't load query history"
                onRetry={retryHistory}
                data-attr="warehouse-history-retry"
            />
        )
    } else if (!history) {
        body = <Skeleton className="h-48 w-full" />
    } else {
        body = (
            <div className={historyLoading ? 'flex flex-col gap-3 opacity-60' : 'flex flex-col gap-3'}>
                <DataTable
                    columns={COLUMNS}
                    data={historyRows}
                    size="sm"
                    fullWidth
                    getRowId={(row) => String(row.id)}
                    onRowClick={(row) => toggleHistoryRow(row.id)}
                    empty={
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>No queries found</EmptyTitle>
                                <EmptyDescription>
                                    No queries match these filters. Try a longer time range.
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    }
                />
                {hasMoreHistory ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <Button
                            loading={historyLoading}
                            disabled={historyLoading}
                            onClick={() => loadMoreHistory()}
                            data-attr="warehouse-history-load-more"
                        >
                            Load more
                        </Button>
                        {loadMoreFailed ? (
                            <Text size="sm" variant="destructive">
                                Couldn't load more queries. Try again.
                            </Text>
                        ) : null}
                    </div>
                ) : null}
            </div>
        )
    }

    return (
        <Card data-attr="warehouse-query-history">
            <CardHeader>
                <CardTitle>History</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
                <div className="flex flex-wrap items-end gap-3">
                    <WarehouseFilterSelect
                        label="Status"
                        value={statusFilter}
                        options={STATUS_OPTIONS}
                        onChange={(value) => setStatusFilter(value as HistoryStatusFilter)}
                        data-attr="warehouse-history-filter-status"
                    />
                    <WarehouseFilterSelect
                        label="Source"
                        value={sourceFilter ?? 'all'}
                        options={[{ value: 'all', label: 'All sources' }, ...sourceOptions]}
                        onChange={(value) => setSourceFilter(value === 'all' ? null : value)}
                        data-attr="warehouse-history-filter-source"
                    />
                    <WarehouseFilterSelect
                        label="Login"
                        value={principalFilter ?? 'all'}
                        options={[{ value: 'all', label: 'All logins' }, ...principalOptions]}
                        onChange={(value) => setPrincipalFilter(value === 'all' ? null : value)}
                        data-attr="warehouse-history-filter-login"
                    />
                    <WarehouseFilterSelect
                        label="Time range"
                        value={rangeFilter}
                        options={RANGE_OPTIONS}
                        onChange={(value) => setRangeFilter(value as HistoryRangeFilter)}
                        data-attr="warehouse-history-filter-range"
                    />
                </div>
                {body}
            </CardContent>
        </Card>
    )
}
