import { useActions, useValues } from 'kea'

import { Button, DataTable, type DataTableProps, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { ManagedWarehouseSourceTableStatusApi } from '../../generated/api.schemas'
import { formatCount } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
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

/** The tables of the source whose chevron is open, loaded the first time it opens. */
export function WarehousePipelineSourceTables(): JSX.Element | null {
    const { expandedSource, expandedSourceSchemas, schemasFailed, schemasLoading } =
        useValues(warehousePipelineHealthLogic)
    const { toggleSource, retrySourceSchemas } = useActions(warehousePipelineHealthLogic)

    if (!expandedSource) {
        return null
    }
    const sourceId = expandedSource.source_id

    let content: JSX.Element
    if (expandedSourceSchemas) {
        content =
            expandedSourceSchemas.length === 0 ? (
                <Text size="sm" variant="muted" className="px-3 py-4" render={<div />}>
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
                title={`Couldn't load tables in ${expandedSource.source_name}`}
                onRetry={() => retrySourceSchemas(sourceId)}
                data-attr="warehouse-pipeline-health-schemas-retry"
            />
        )
    } else {
        content = <Skeleton className="mx-3 h-24 w-[calc(100%-1.5rem)]" />
    }

    return (
        <div id="warehouse-pipeline-health-source-tables">
            <WarehouseSection
                title={`Tables in ${expandedSource.source_name}`}
                flush={!!expandedSourceSchemas?.length}
                data-attr="warehouse-pipeline-health-source-tables"
                controls={
                    <Button
                        size="sm"
                        onClick={() => toggleSource(sourceId)}
                        data-attr="warehouse-pipeline-health-source-hide"
                    >
                        Hide
                    </Button>
                }
            >
                {content}
            </WarehouseSection>
        </div>
    )
}
