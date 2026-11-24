import { useActions, useValues } from 'kea'

import {
    DataTable,
    type DataTableProps,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { ManagedWarehouseSourceTableStatusApi } from '../../generated/api.schemas'
import { formatCount } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { humanizeStatus } from './pipelineHealthStats'
import { WarehouseLandingCell } from './WarehouseLandingCell'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

// Declared at module level so TanStack keeps the cell identities across refreshes.
const COLUMNS: DataTableProps<ManagedWarehouseSourceTableStatusApi, unknown>['columns'] = [
    {
        id: 'table',
        header: 'Table',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => (
            <LinkPrimitive
                to={urls.dataWarehouseSourceSchema(`managed-${row.original.source_id}`, row.original.schema_id)}
                onClick={() => warehousePipelineHealthLogic.actions.linkClicked('schema')}
                className="block max-w-56 truncate"
                title={row.original.table_name}
                data-attr="warehouse-pipeline-health-schema-link"
            >
                {row.original.table_name}
            </LinkPrimitive>
        ),
    },
    {
        id: 'source_sync',
        header: 'Source sync',
        enableSorting: false,
        cell: ({ row }) => (
            <div className="flex items-center gap-2 whitespace-nowrap">
                <span>{humanizeStatus(row.original.sync_status)}</span>
                {row.original.last_synced_at ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        <WarehouseTime iso={row.original.last_synced_at} />
                    </Text>
                ) : null}
                {row.original.last_sync_rows !== null ? (
                    <Text size="xs" variant="muted" className="tabular-nums" render={<span />}>
                        {formatCount(row.original.last_sync_rows)} rows
                    </Text>
                ) : null}
                {row.original.sync_error ? (
                    <Text
                        size="xs"
                        variant="destructive"
                        className="block max-w-48 truncate"
                        title={row.original.sync_error}
                        render={<span />}
                    >
                        {row.original.sync_error}
                    </Text>
                ) : null}
            </div>
        ),
    },
    {
        id: 'warehouse',
        header: 'Warehouse',
        enableSorting: false,
        cell: ({ row }) => (
            <WarehouseLandingCell
                landingState={row.original.landing_state}
                appliedAt={row.original.last_applied_at}
                pendingSince={row.original.pending_since}
                error={row.original.workflow_error}
            />
        ),
    },
]

/** A dialog with the tables of one source, loaded the first time it opens. */
export function WarehousePipelineSourceTables(): JSX.Element {
    const { expandedSource, expandedSourceSchemas, schemasFailed, schemasLoading } =
        useValues(warehousePipelineHealthLogic)
    const { toggleSource, retrySourceSchemas } = useActions(warehousePipelineHealthLogic)
    const sourceId = expandedSource?.source_id

    let content: JSX.Element | null = null
    if (!sourceId) {
        content = null
    } else if (expandedSourceSchemas) {
        content =
            expandedSourceSchemas.length === 0 ? (
                <Text size="sm" variant="muted" render={<div />}>
                    This source has no tables yet.
                </Text>
            ) : (
                <DataTable
                    columns={COLUMNS}
                    data={expandedSourceSchemas}
                    size="sm"
                    fullWidth
                    getRowId={(row) => row.schema_id}
                />
            )
    } else if (schemasFailed[sourceId] && !schemasLoading[sourceId]) {
        content = (
            <WarehouseResourceError
                title="Couldn't load tables"
                onRetry={() => retrySourceSchemas(sourceId)}
                data-attr="warehouse-pipeline-health-schemas-retry"
            />
        )
    } else {
        content = <Skeleton className="h-24 w-full" />
    }

    return (
        <Dialog
            open={!!sourceId}
            onOpenChange={(open) => {
                if (!open && sourceId) {
                    toggleSource(sourceId)
                }
            }}
        >
            <DialogContent size="wide" data-attr="warehouse-pipeline-health-source-tables">
                <DialogHeader>
                    <DialogTitle>{expandedSource ? `Tables in ${expandedSource.source_name}` : 'Tables'}</DialogTitle>
                    <DialogDescription>
                        The latest source sync of each table, and whether it has landed in your warehouse.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>{content}</DialogBody>
            </DialogContent>
        </Dialog>
    )
}
