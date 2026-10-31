import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconDatabase, IconGroups, IconPeople, IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type { ManagedWarehouseSourceSummaryApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { DatasetCard } from './DatasetCard'
import { managedWarehouseDataStatusLogic } from './managedWarehouseDataStatusLogic'
import { SourceSchemasModal } from './SourceSchemasModal'
import { sourceSchemasModalLogic } from './sourceSchemasModalLogic'
import { STATUS_SEVERITY, StatusTag } from './warehouseStatusDisplay'

export function OverviewTab(): JSX.Element {
    const { managedWarehouseDataStatus, managedWarehouseDataStatusLoading } = useValues(managedWarehouseDataStatusLogic)
    const { loadManagedWarehouseDataStatus } = useActions(managedWarehouseDataStatusLogic)
    const { loadSourceSchemas } = useActions(sourceSchemasModalLogic)

    const openSourceSchemas = (source: ManagedWarehouseSourceSummaryApi): void => {
        // pinned: analytics event and property names, renaming breaks dashboards
        posthog.capture('managed warehouse source schemas opened', {
            readiness_state: source.readiness_state,
            source_type: source.source_type,
        })
        loadSourceSchemas({ sourceId: source.source_id, sourceName: source.source_name })
    }

    const sourceSummaryColumns: LemonTableColumns<ManagedWarehouseSourceSummaryApi> = [
        {
            title: 'Source',
            key: 'source',
            render: (_, source) => (
                <LemonTableLink
                    title={source.source_name}
                    description={source.source_type}
                    to={urls.dataWarehouseSource(`managed-${source.source_id}`, 'schemas')}
                    data-attr="managed-warehouse-source-schemas"
                    onClick={(e) => {
                        // A plain click opens the table list. Cmd or Ctrl-click skips this handler
                        // and opens the source page in a new tab.
                        e.preventDefault()
                        e.stopPropagation()
                        openSourceSchemas(source)
                    }}
                />
            ),
            sorter: (a, b) => a.source_name.localeCompare(b.source_name),
        },
        {
            title: 'Warehouse status',
            key: 'readiness_state',
            render: (_, source) => (
                <div className="space-y-1 max-w-96">
                    <StatusTag readinessState={source.readiness_state} />
                    <div className="text-xs text-muted break-words">{source.detail}</div>
                </div>
            ),
            sorter: (a, b) => STATUS_SEVERITY[a.readiness_state] - STATUS_SEVERITY[b.readiness_state],
        },
        {
            title: 'Schemas applied',
            key: 'applied_schemas',
            render: (_, source) => `${source.applied_schemas} / ${source.total_schemas}`,
            sorter: (a, b) => a.applied_schemas / a.total_schemas - b.applied_schemas / b.total_schemas,
        },
        {
            title: 'Last source import',
            dataIndex: 'last_synced_at',
            render: (lastSyncedAt) =>
                typeof lastSyncedAt === 'string' ? humanFriendlyDetailedTime(lastSyncedAt) : 'Not synced yet',
            sorter: (a, b) => new Date(a.last_synced_at ?? 0).getTime() - new Date(b.last_synced_at ?? 0).getTime(),
        },
        {
            title: 'Applied to warehouse',
            dataIndex: 'last_applied_at',
            render: (lastAppliedAt) =>
                typeof lastAppliedAt === 'string' ? humanFriendlyDetailedTime(lastAppliedAt) : 'Not recorded yet',
            sorter: (a, b) => new Date(a.last_applied_at ?? 0).getTime() - new Date(b.last_applied_at ?? 0).getTime(),
        },
    ]

    if (managedWarehouseDataStatusLoading && !managedWarehouseDataStatus) {
        return (
            <div className="mt-4 flex items-center gap-2 text-muted">
                <Spinner />
                <span>Loading warehouse data status...</span>
            </div>
        )
    }

    if (!managedWarehouseDataStatus) {
        return (
            <LemonBanner type="error" className="mt-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <span>Warehouse data status could not be loaded.</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={() => loadManagedWarehouseDataStatus()}
                        loading={managedWarehouseDataStatusLoading}
                    >
                        Try again
                    </LemonButton>
                </div>
            </LemonBanner>
        )
    }

    const bannerType =
        managedWarehouseDataStatus.overall_readiness_state === 'needs_attention'
            ? 'error'
            : managedWarehouseDataStatus.overall_readiness_state === 'up_to_date'
              ? 'success'
              : 'info'

    return (
        <div className="@container mt-4 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h2 className="mb-1">Warehouse data readiness</h2>
                    <p className="text-muted mb-0">
                        Track historical backfills and the workflows applying source imports to your warehouse.
                    </p>
                </div>
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={() => loadManagedWarehouseDataStatus()}
                    loading={managedWarehouseDataStatusLoading}
                >
                    Refresh
                </LemonButton>
            </div>

            <LemonBanner type={bannerType}>
                <div className="flex items-center gap-2">
                    <StatusTag readinessState={managedWarehouseDataStatus.overall_readiness_state} />
                    <span>Status checked {humanFriendlyDetailedTime(managedWarehouseDataStatus.generated_at)}</span>
                </div>
            </LemonBanner>

            <div className="grid grid-cols-1 @min-[40rem]:grid-cols-2 @min-[64rem]:grid-cols-3 gap-4">
                <DatasetCard
                    title="Events"
                    description="Historical events and daily warehouse updates"
                    icon={<IconDatabase />}
                    status={managedWarehouseDataStatus.events}
                />
                <DatasetCard
                    title="Persons"
                    description="Historical persons and daily warehouse updates"
                    icon={<IconPeople />}
                    status={managedWarehouseDataStatus.persons}
                />
                <DatasetCard
                    title="Groups"
                    description="Historical groups and warehouse updates"
                    icon={<IconGroups />}
                    status={managedWarehouseDataStatus.groups}
                />
            </div>

            <LemonCard className="p-0 overflow-hidden" hoverEffect={false}>
                <div className="p-4 flex items-start justify-between gap-3 border-b">
                    <div>
                        <h3 className="mb-1">Imported source tables</h3>
                        <p className="text-xs text-muted mb-0">
                            Shows your warehouse source imports, including tables with sync paused.{' '}
                            <Link to={urls.sources()}>Manage sources</Link>
                        </p>
                    </div>
                    <StatusTag readinessState={managedWarehouseDataStatus.sources.readiness_state} />
                </div>
                {managedWarehouseDataStatus.sources.sources.length ? (
                    <LemonTable
                        embedded
                        columns={sourceSummaryColumns}
                        dataSource={managedWarehouseDataStatus.sources.sources}
                        rowKey="source_id"
                        pagination={{ pageSize: 20 }}
                        onRow={(source) => ({
                            onClick: () => openSourceSchemas(source),
                            className: 'cursor-pointer',
                        })}
                    />
                ) : (
                    <div className="p-6 text-muted">No imported source tables are configured for this warehouse.</div>
                )}
            </LemonCard>

            <SourceSchemasModal />
        </div>
    )
}
