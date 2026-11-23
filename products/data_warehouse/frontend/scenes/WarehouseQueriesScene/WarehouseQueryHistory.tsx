import { useActions, useValues } from 'kea'

import { Button, DataTable, type DataTableProps, Skeleton, Text } from '@posthog/quill'

import type { QueryHistoryRowApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import {
    formatAbsoluteTime,
    formatBytes,
    formatCount,
    formatDuration,
    formatUsd,
} from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { WarehouseFilterSelect } from './WarehouseFilterSelect'
import { type HistoryRangeFilter, type HistoryStatusFilter, warehouseQueriesLogic } from './warehouseQueriesLogic'
import { WarehouseSqlBlock } from './WarehouseSqlBlock'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const STATUS_OPTIONS: { value: HistoryStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
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

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col">
            <Text size="xs" variant="muted" render={<dt />}>
                {label}
            </Text>
            <Text size="xs" className="min-w-0 break-all" render={<dd className="m-0" />}>
                {children}
            </Text>
        </div>
    )
}

function QueryCell({ row }: { row: QueryHistoryRowApi }): JSX.Element {
    const { expandedRowIds, teamNames } = useValues(warehouseQueriesLogic)
    const expanded = expandedRowIds.includes(row.id)
    const error = errorSummary(row)

    if (!expanded) {
        return row.query === null ? (
            <Text size="xs" variant="muted">
                SQL hidden
            </Text>
        ) : (
            <code className="block max-w-52 truncate font-mono text-xs" title="Click the row to see the full query">
                {row.query}
            </code>
        )
    }
    return (
        <div className="flex w-[32rem] max-w-full min-w-[24rem] flex-col gap-3 py-2" data-row-click-ignore>
            {row.query === null ? (
                <Text size="xs" variant="muted">
                    SQL hidden: you don't have access to this project
                </Text>
            ) : (
                <WarehouseSqlBlock sql={row.query} />
            )}
            <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-2 @lg/warehouse-queries:grid-cols-2">
                <DetailRow label="Query id">
                    <code className="font-mono">{row.query_id}</code>
                </DetailRow>
                <DetailRow label="Login">
                    <code className="font-mono">{row.principal}</code>
                </DetailRow>
                <DetailRow label="Project">
                    {row.team_id == null ? '-' : (teamNames[row.team_id] ?? `Project ${row.team_id}`)}
                </DetailRow>
                <DetailRow label="Queued">{formatDuration(row.queued_ms)}</DetailRow>
                <DetailRow label="Started">{formatAbsoluteTime(row.created_at) || '-'}</DetailRow>
                <DetailRow label="Finished">{formatAbsoluteTime(row.completed_at) || '-'}</DetailRow>
                {row.state === 'FAILED' ? <DetailRow label="Error">{error ?? 'Unknown'}</DetailRow> : null}
            </dl>
        </div>
    )
}

const numeric = (content: React.ReactNode): JSX.Element => (
    <span className="whitespace-nowrap tabular-nums">{content}</span>
)

// Declared at module level so TanStack keeps the cell identities across renders.
const COLUMNS: DataTableProps<QueryHistoryRowApi, unknown>['columns'] = [
    {
        id: 'created_at',
        header: 'Time',
        enableSorting: false,
        cell: ({ row }) => <WarehouseTime iso={row.original.created_at} />,
    },
    {
        id: 'query',
        header: 'Query',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => <QueryCell row={row.original} />,
    },
    {
        accessorKey: 'principal_label',
        header: 'Login',
        enableSorting: false,
        cell: ({ row }) => (
            <span className="block max-w-28 truncate" title={row.original.principal}>
                {row.original.principal_label}
            </span>
        ),
    },
    {
        accessorKey: 'source_label',
        header: 'Source',
        enableSorting: false,
        cell: ({ row }) => (
            <span className="block max-w-24 truncate" title={row.original.source}>
                {row.original.source_label}
            </span>
        ),
    },
    {
        id: 'state',
        header: 'Status',
        enableSorting: false,
        cell: ({ row }) => {
            const failed = row.original.state === 'FAILED'
            const error = errorSummary(row.original)
            return (
                <div className="flex items-center gap-2 whitespace-nowrap">
                    <WarehouseStatusBadge status={row.original.state} />
                    {failed && error ? (
                        <code className="block max-w-20 truncate font-mono text-xs text-muted-foreground" title={error}>
                            {error}
                        </code>
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
        cell: ({ row }) => numeric(formatDuration(row.original.elapsed_ms)),
    },
    {
        id: 'billable_bytes',
        header: 'Scanned',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => numeric(formatBytes(row.original.billable_bytes)),
    },
    {
        id: 'estimated_cost_usd',
        header: 'Est. cost',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => numeric(row.original.billable ? formatUsd(row.original.estimated_cost_usd) : 'Not billed'),
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
            <div className="px-3">
                <WarehouseResourceError
                    title="Couldn't load query history"
                    onRetry={retryHistory}
                    data-attr="warehouse-history-retry"
                />
            </div>
        )
    } else if (!history) {
        body = <Skeleton className="mx-3 h-40 w-[calc(100%-1.5rem)]" />
    } else {
        body = (
            <div className={historyLoading ? 'flex flex-col opacity-60' : 'flex flex-col'}>
                <DataTable
                    columns={COLUMNS}
                    data={historyRows}
                    size="sm"
                    fullWidth
                    getRowId={(row) => String(row.id)}
                    onRowClick={(row) => toggleHistoryRow(row.id)}
                    empty={
                        <Text size="sm" variant="muted" className="px-3 py-4">
                            No queries match these filters. Try a longer time range.
                        </Text>
                    }
                />
                {historyRows.length > 0 ? (
                    <div className="flex flex-col items-center gap-1 pt-3">
                        <Text size="xs" variant="muted">
                            Showing {formatCount(historyRows.length)} queries
                        </Text>
                        {hasMoreHistory ? (
                            <Button
                                size="sm"
                                loading={historyLoading}
                                disabled={historyLoading}
                                onClick={() => loadMoreHistory()}
                                data-attr="warehouse-history-load-more"
                            >
                                Load more
                            </Button>
                        ) : null}
                        {loadMoreFailed ? (
                            <Text size="xs" variant="destructive">
                                Couldn't load more queries. Try again.
                            </Text>
                        ) : null}
                    </div>
                ) : null}
            </div>
        )
    }

    return (
        <WarehouseSection
            title="History"
            flush
            data-attr="warehouse-query-history"
            controls={
                <>
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
                        options={[{ value: 'all', label: 'All' }, ...sourceOptions]}
                        onChange={(value) => setSourceFilter(value === 'all' ? null : value)}
                        data-attr="warehouse-history-filter-source"
                    />
                    <WarehouseFilterSelect
                        label="Login"
                        value={principalFilter ?? 'all'}
                        options={[{ value: 'all', label: 'All' }, ...principalOptions]}
                        onChange={(value) => setPrincipalFilter(value === 'all' ? null : value)}
                        data-attr="warehouse-history-filter-login"
                    />
                    <WarehouseFilterSelect
                        label="Time"
                        value={rangeFilter}
                        options={RANGE_OPTIONS}
                        onChange={(value) => setRangeFilter(value as HistoryRangeFilter)}
                        data-attr="warehouse-history-filter-range"
                    />
                </>
            }
        >
            {body}
        </WarehouseSection>
    )
}
