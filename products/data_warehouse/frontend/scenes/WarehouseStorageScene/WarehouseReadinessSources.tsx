import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { DataTable, type DataTableProps, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { ManagedWarehouseSourceSummaryApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { managedWarehouseDataStatusLogic } from '../DataOpsScene/tabs/managedWarehouseDataStatusLogic'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'
import { WarehouseSectionLink } from '../WarehouseConsole/WarehouseSectionLink'
import { WarehouseStatusBadge } from '../WarehouseConsole/WarehouseStatusBadge'
import { WarehouseTime } from '../WarehouseConsole/WarehouseTime'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const sourceUrl = (source: ManagedWarehouseSourceSummaryApi): string =>
    urls.dataWarehouseSource(`managed-${source.source_id}`, 'schemas')

function trackOpened(source: ManagedWarehouseSourceSummaryApi): void {
    posthog.capture('warehouse readiness source opened', {
        readiness_state: source.readiness_state,
        source_type: source.source_type,
    })
}

// Declared at module level so TanStack keeps the cell identities across refreshes.
const COLUMNS: DataTableProps<ManagedWarehouseSourceSummaryApi, unknown>['columns'] = [
    {
        accessorKey: 'source_name',
        header: 'Source',
        meta: { expand: true },
        cell: ({ row }) => (
            <LinkPrimitive
                to={sourceUrl(row.original)}
                onClick={() => trackOpened(row.original)}
                className="block max-w-56 truncate"
                title={`${row.original.source_name} (${row.original.source_type})`}
                data-attr="warehouse-readiness-source-link"
            >
                {row.original.source_name}
                <span className="text-muted-foreground"> · {row.original.source_type}</span>
            </LinkPrimitive>
        ),
    },
    {
        accessorKey: 'readiness_state',
        header: 'Status',
        enableSorting: false,
        cell: ({ row }) => (
            <div className="flex items-center gap-2">
                <WarehouseStatusBadge status={row.original.readiness_state} />
                <span className="block max-w-56 truncate text-xs text-muted-foreground" title={row.original.detail}>
                    {row.original.detail}
                </span>
            </div>
        ),
    },
    {
        id: 'schemas',
        header: 'Schemas applied',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (
            <span className="whitespace-nowrap tabular-nums">
                {row.original.applied_schemas} / {row.original.total_schemas}
            </span>
        ),
    },
    {
        accessorKey: 'last_synced_at',
        header: 'Last import',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) =>
            row.original.last_synced_at ? <WarehouseTime iso={row.original.last_synced_at} /> : 'Not synced yet',
    },
    {
        accessorKey: 'last_applied_at',
        header: 'Applied to warehouse',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) =>
            row.original.last_applied_at ? <WarehouseTime iso={row.original.last_applied_at} /> : 'Not recorded yet',
    },
]

export function WarehouseReadinessSources(): JSX.Element | null {
    const { managedWarehouseDataStatus } = useValues(managedWarehouseDataStatusLogic)
    if (!managedWarehouseDataStatus) {
        return null
    }
    const sources = managedWarehouseDataStatus.sources.sources
    return (
        <WarehouseSection
            title="Imported sources"
            description="Source imports applied to your warehouse, including tables with sync paused."
            flush
            data-attr="warehouse-readiness-sources"
            controls={
                <>
                    <WarehouseStatusBadge status={managedWarehouseDataStatus.sources.readiness_state} />
                    <WarehouseSectionLink to={urls.sources()} data-attr="warehouse-readiness-manage-sources">
                        Manage sources
                    </WarehouseSectionLink>
                </>
            }
        >
            <DataTable
                columns={COLUMNS}
                data={sources}
                size="sm"
                fullWidth
                pageSize={sources.length > 20 ? 20 : undefined}
                getRowId={(row) => row.source_id}
                onRowClick={(row) => {
                    trackOpened(row)
                    router.actions.push(sourceUrl(row))
                }}
                empty={
                    <Text size="sm" variant="muted" className="px-3 py-4">
                        No imported sources are configured for this warehouse.
                    </Text>
                }
            />
        </WarehouseSection>
    )
}
