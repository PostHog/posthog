import { useActions, useValues } from 'kea'

import {
    DataTable,
    type DataTableProps,
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
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

import { duration, stateLabel } from '../DataOpsScene/tabs/trinoMonitoringFormat'
import { formatBytes } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
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
            variant="destructive"
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
    { accessorKey: 'loginLabel', header: 'Login' },
    {
        accessorKey: 'state',
        header: 'State',
        cell: ({ row }) => (
            <Badge variant={row.original.state === 'queued' ? 'warning' : 'info'}>
                {stateLabel(row.original.state)}
            </Badge>
        ),
    },
    {
        accessorKey: 'elapsed_ms',
        header: 'Elapsed',
        meta: { align: 'right' },
        cell: ({ row }) => duration(row.original.elapsed_ms),
    },
    {
        accessorKey: 'physical_input_bytes',
        header: 'Scanned so far',
        meta: { align: 'right' },
        cell: ({ row }) =>
            row.original.physical_input_bytes > 0 ? formatBytes(row.original.physical_input_bytes) : '-',
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
            <WarehouseResourceError
                title="Couldn't load running queries"
                onRetry={retryRunning}
                data-attr="warehouse-running-retry"
            />
        )
    } else if (!running && runningLoading) {
        body = <Skeleton className="h-24 w-full" />
    } else if (running && !running.available) {
        body = (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>Live query data is unavailable</EmptyTitle>
                    <EmptyDescription>The list refreshes on its own. Try again in a moment.</EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    } else {
        body = (
            <div className="flex flex-col gap-2">
                <DataTable
                    columns={COLUMNS}
                    data={runningRows}
                    size="sm"
                    fullWidth
                    empty={
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>No queries running</EmptyTitle>
                                <EmptyDescription>Queries show up here while they run.</EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    }
                />
                {runningFailed ? (
                    <Text size="xs" variant="muted">
                        The last refresh failed. Showing the previous list.
                    </Text>
                ) : running?.queries_truncated ? (
                    <Text size="xs" variant="muted">
                        Showing the longest running queries only.
                    </Text>
                ) : null}
            </div>
        )
    }

    return (
        <Card data-attr="warehouse-running-queries">
            <CardHeader>
                <CardTitle>Running now</CardTitle>
            </CardHeader>
            <CardContent>{body}</CardContent>
            <CancelDialog />
        </Card>
    )
}
