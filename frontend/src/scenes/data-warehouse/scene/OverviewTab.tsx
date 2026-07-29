import { useActions, useValues } from 'kea'

import { IconDatabase, IconPeople, IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type {
    ManagedWarehouseDatasetStatusApi,
    ManagedWarehouseSourceSummaryApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { managedWarehouseDataStatusLogic } from './managedWarehouseDataStatusLogic'
import { SourceSchemasModal } from './SourceSchemasModal'
import { sourceSchemasModalLogic } from './sourceSchemasModalLogic'
import { STATUS_SEVERITY, StatusTag } from './warehouseStatusDisplay'

function DatasetCard({
    title,
    description,
    icon,
    status,
}: {
    title: string
    description: string
    icon: JSX.Element
    status: ManagedWarehouseDatasetStatusApi
}): JSX.Element {
    const hasProgress = status.total_partitions !== null && status.total_partitions > 0
    const progress = hasProgress ? Math.round((status.completed_partitions / status.total_partitions!) * 100) : null

    return (
        <LemonCard className="p-4 space-y-4" hoverEffect={false}>
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                    <div className="text-xl text-muted mt-0.5">{icon}</div>
                    <div>
                        <h3 className="mb-1">{title}</h3>
                        <p className="text-muted mb-0">{description}</p>
                    </div>
                </div>
                <StatusTag readinessState={status.readiness_state} />
            </div>
            <div className="border-t pt-4 space-y-3">
                <p className="mb-0">{status.detail}</p>
                {progress !== null && (
                    <div className="space-y-1">
                        <div className="flex justify-between text-xs text-muted">
                            <span>Historical backfill</span>
                            <span>
                                {status.completed_partitions} / {status.total_partitions}
                            </span>
                        </div>
                        <LemonProgress percent={progress} />
                    </div>
                )}
                {status.current_partition && (
                    <div className="text-xs text-muted">
                        Current partition: <code>{status.current_partition}</code>
                    </div>
                )}
                {status.last_updated_at && (
                    <div className="text-xs text-muted">
                        Updated {humanFriendlyDetailedTime(status.last_updated_at)}
                    </div>
                )}
            </div>
        </LemonCard>
    )
}

export function OverviewTab(): JSX.Element {
    const { managedWarehouseDataStatus, managedWarehouseDataStatusLoading } = useValues(managedWarehouseDataStatusLogic)
    const { loadManagedWarehouseDataStatus } = useActions(managedWarehouseDataStatusLogic)
    const { loadSourceSchemas } = useActions(sourceSchemasModalLogic)

    const sourceSummaryColumns: LemonTableColumns<ManagedWarehouseSourceSummaryApi> = [
        {
            title: 'Source',
            key: 'source',
            render: (_, source) => (
                <div>
                    <div className="font-medium">{source.source_name}</div>
                    <div className="text-xs text-muted">{source.source_type}</div>
                </div>
            ),
            sorter: (a, b) => a.source_name.localeCompare(b.source_name),
        },
        {
            title: 'Warehouse status',
            key: 'readiness_state',
            render: (_, source) => (
                <div className="space-y-1 max-w-96">
                    <StatusTag readinessState={source.readiness_state} />
                    <div className="text-xs text-muted">{source.detail}</div>
                </div>
            ),
            sorter: (a, b) => STATUS_SEVERITY[a.readiness_state] - STATUS_SEVERITY[b.readiness_state],
        },
        {
            title: 'Schemas backfilled',
            key: 'backfilled_schemas',
            render: (_, source) => `${source.backfilled_schemas} / ${source.total_schemas}`,
            sorter: (a, b) => a.backfilled_schemas / a.total_schemas - b.backfilled_schemas / b.total_schemas,
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
                <div className="flex items-center justify-between gap-3">
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
        <div className="mt-4 space-y-4">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <h2 className="mb-1">Warehouse data readiness</h2>
                    <p className="text-muted mb-0">
                        Track historical backfills and whether recent source imports have reached your warehouse.
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

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
            </div>

            <LemonCard className="p-0 overflow-hidden" hoverEffect={false}>
                <div className="p-4 flex items-start justify-between gap-3 border-b">
                    <div>
                        <h3 className="mb-1">Imported source tables</h3>
                        <p className="text-xs text-muted mb-0">
                            Reflects the warehouse source imports currently enabled to sync.{' '}
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
                            onClick: () =>
                                loadSourceSchemas({ sourceId: source.source_id, sourceName: source.source_name }),
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
