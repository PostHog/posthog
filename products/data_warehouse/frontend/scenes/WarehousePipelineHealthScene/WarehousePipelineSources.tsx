import { useValues } from 'kea'

import { DataTable, type DataTableProps, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { ManagedWarehouseSourceSummaryApi } from '../../generated/api.schemas'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseSectionLink } from '../WarehouseConsole/WarehouseSectionLink'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'
import { tablesInSync } from './pipelineHealthStats'
import { WarehouseLandingCell } from './WarehouseLandingCell'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'
import { WarehousePipelineSourceToggle } from './WarehousePipelineSourceToggle'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

// Declared at module level so TanStack keeps the cell identities across refreshes.
const COLUMNS: DataTableProps<ManagedWarehouseSourceSummaryApi, unknown>['columns'] = [
    {
        id: 'source',
        header: 'Source',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => (
            <div className="flex items-center gap-1">
                <WarehousePipelineSourceToggle
                    sourceId={row.original.source_id}
                    sourceName={row.original.source_name}
                />
                <LinkPrimitive
                    to={urls.dataWarehouseSource(`managed-${row.original.source_id}`, 'schemas')}
                    onClick={() => warehousePipelineHealthLogic.actions.linkClicked('source')}
                    className="block max-w-56 truncate"
                    title={`${row.original.source_name} (${row.original.source_type})`}
                    data-attr="warehouse-pipeline-health-source-link"
                >
                    {row.original.source_name}
                    <span className="text-muted-foreground"> · {row.original.source_type}</span>
                </LinkPrimitive>
            </div>
        ),
    },
    {
        id: 'source_sync',
        header: 'Source sync',
        enableSorting: false,
        cell: ({ row }) => (
            <div className="flex items-center gap-2 whitespace-nowrap">
                {row.original.last_synced_at ? (
                    <WarehouseTime iso={row.original.last_synced_at} />
                ) : (
                    <span className="text-muted-foreground">Not synced yet</span>
                )}
                {row.original.sync_failed_schemas > 0 ? (
                    <Text size="xs" variant="destructive" render={<span />}>
                        {row.original.sync_failed_schemas} failing
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
            />
        ),
    },
    {
        id: 'tables',
        header: 'Tables',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => <span className="whitespace-nowrap tabular-nums">{tablesInSync(row.original)}</span>,
    },
]

/** One row per imported source: the upstream sync, then the stage this page is about, the warehouse. */
export function WarehousePipelineSources(): JSX.Element {
    const { sources } = useValues(warehousePipelineHealthLogic)

    return (
        <WarehouseSection
            title="Sources"
            description="Sources sync in batches on a schedule. The warehouse stage shows whether each batch has landed."
            flush
            data-attr="warehouse-pipeline-health-sources"
            controls={
                <WarehouseSectionLink
                    to={urls.sources()}
                    onClick={() => warehousePipelineHealthLogic.actions.linkClicked('sources')}
                    data-attr="warehouse-pipeline-health-manage-sources"
                >
                    Manage sources
                </WarehouseSectionLink>
            }
        >
            <DataTable
                columns={COLUMNS}
                data={sources}
                size="sm"
                fullWidth
                pageSize={sources.length > 20 ? 20 : undefined}
                getRowId={(row) => row.source_id}
                empty={
                    <Text size="sm" variant="muted" className="px-3 py-4" render={<div />}>
                        No sources import into this warehouse yet.{' '}
                        <LinkPrimitive
                            to={urls.sources()}
                            onClick={() => warehousePipelineHealthLogic.actions.linkClicked('sources')}
                            data-attr="warehouse-pipeline-health-add-source"
                        >
                            Add a source
                        </LinkPrimitive>
                    </Text>
                }
            />
        </WarehouseSection>
    )
}
