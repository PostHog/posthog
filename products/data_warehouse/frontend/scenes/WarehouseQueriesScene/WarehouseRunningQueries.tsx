import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    DataTable,
    type DataTableProps,
    Skeleton,
    Text,
} from '@posthog/quill'

import { formatBytes, formatDuration } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'
import { type RunningQueryRow, warehouseQueriesLogic } from './warehouseQueriesLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

function CancelCell({ row }: { row: RunningQueryRow }): JSX.Element | null {
    const { cancelingIds } = useValues(warehouseQueriesLogic)
    const { requestCancel } = useActions(warehouseQueriesLogic)

    if (!row.canCancel) {
        return null
    }
    const canceling = cancelingIds.includes(row.query_id)
    return (
        <Button
            size="sm"
            className="text-destructive-foreground"
            loading={canceling}
            disabled={canceling}
            onClick={() => requestCancel(row.query_id)}
            data-attr="warehouse-query-cancel"
        >
            Cancel
        </Button>
    )
}

// Declared at module level so TanStack keeps the cell identities across the 10 second refreshes.
const COLUMNS: DataTableProps<RunningQueryRow, unknown>['columns'] = [
    {
        accessorKey: 'query',
        header: 'Query',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => (
            <code className="block max-w-96 truncate font-mono text-xs" title={row.original.query}>
                {row.original.query}
            </code>
        ),
    },
    {
        accessorKey: 'loginLabel',
        header: 'Login',
        enableSorting: false,
        cell: ({ row }) => (
            <span className="block max-w-48 truncate" title={row.original.user}>
                {row.original.loginLabel}
            </span>
        ),
    },
    {
        accessorKey: 'state',
        header: 'State',
        enableSorting: false,
        cell: ({ row }) => <WarehouseStatusBadge status={row.original.state} />,
    },
    {
        accessorKey: 'elapsed_ms',
        header: 'Elapsed',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (
            <span className="whitespace-nowrap tabular-nums">{formatDuration(row.original.elapsed_ms)}</span>
        ),
    },
    {
        accessorKey: 'physical_input_bytes',
        header: 'Scanned',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (
            <span className="whitespace-nowrap tabular-nums">
                {row.original.physical_input_bytes > 0 ? formatBytes(row.original.physical_input_bytes) : '-'}
            </span>
        ),
    },
    {
        id: 'actions',
        header: '',
        enableSorting: false,
        meta: { align: 'right', sticky: 'right' },
        cell: ({ row }) => <CancelCell row={row.original} />,
    },
]

function CancelDialog(): JSX.Element {
    const { cancelTarget } = useValues(warehouseQueriesLogic)
    const { dismissCancel, confirmCancel } = useActions(warehouseQueriesLogic)

    return (
        <AlertDialog
            open={cancelTarget !== null}
            onOpenChange={(open) => {
                if (!open) {
                    dismissCancel()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Cancel this query?</AlertDialogTitle>
                    <AlertDialogDescription>
                        The query stops shortly after you confirm. You are still billed for the data it scanned before
                        it stopped.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Keep running</AlertDialogClose>
                    <AlertDialogClose
                        render={<Button variant="destructive" data-attr="warehouse-query-cancel-confirm" />}
                        onClick={() => cancelTarget && confirmCancel(cancelTarget.query_id)}
                    >
                        Cancel query
                    </AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

export function WarehouseRunningQueries(): JSX.Element {
    const { running, runningLoading, runningFailed, runningRows } = useValues(warehouseQueriesLogic)
    const { retryRunning } = useActions(warehouseQueriesLogic)

    let body: JSX.Element
    if (runningFailed && !running) {
        body = (
            <div className="px-3">
                <WarehouseResourceError
                    title="Couldn't load running queries"
                    onRetry={retryRunning}
                    data-attr="warehouse-running-retry"
                />
            </div>
        )
    } else if (!running && runningLoading) {
        body = <Skeleton className="mx-3 h-16 w-[calc(100%-1.5rem)]" />
    } else if (running && !running.available) {
        body = (
            <Text size="sm" variant="muted" className="px-3">
                Live query data is unavailable right now. The list refreshes on its own.
            </Text>
        )
    } else if (runningRows.length === 0) {
        body = (
            <Text size="sm" variant="muted" className="px-3">
                No queries are running.
            </Text>
        )
    } else {
        body = (
            <>
                <DataTable columns={COLUMNS} data={runningRows} size="sm" fullWidth />
                {runningFailed ? (
                    <Text size="xs" variant="muted" className="px-3 pt-2">
                        The last refresh failed. Showing the previous list.
                    </Text>
                ) : running?.queries_truncated ? (
                    <Text size="xs" variant="muted" className="px-3 pt-2">
                        Showing the longest running queries only.
                    </Text>
                ) : null}
            </>
        )
    }

    return (
        <WarehouseSection title="Running now" flush={runningRows.length > 0} data-attr="warehouse-running-queries">
            {body}
            <CancelDialog />
        </WarehouseSection>
    )
}
