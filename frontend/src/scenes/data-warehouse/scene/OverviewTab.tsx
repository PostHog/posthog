import { useActions, useValues } from 'kea'

import { IconDatabase, IconPeople, IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type {
    ManagedWarehouseDatasetStatusApi,
    ManagedWarehouseReadinessStateEnumApi,
    ManagedWarehouseSourceTableStatusApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { managedWarehouseDataStatusLogic } from './managedWarehouseDataStatusLogic'

const STATUS_LABELS: Record<ManagedWarehouseReadinessStateEnumApi, string> = {
    not_configured: 'Not configured',
    waiting: 'Waiting',
    backfilling: 'Backfilling',
    catching_up: 'Catching up',
    up_to_date: 'Up to date',
    needs_attention: 'Needs attention',
    unknown: 'Status unavailable',
}

const STATUS_TAG_TYPES: Record<ManagedWarehouseReadinessStateEnumApi, LemonTagType> = {
    not_configured: 'muted',
    waiting: 'warning',
    backfilling: 'primary',
    catching_up: 'primary',
    up_to_date: 'success',
    needs_attention: 'danger',
    unknown: 'muted',
}

function StatusTag({ readinessState }: { readinessState: ManagedWarehouseReadinessStateEnumApi }): JSX.Element {
    return <LemonTag type={STATUS_TAG_TYPES[readinessState]}>{STATUS_LABELS[readinessState]}</LemonTag>
}

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
        <LemonCard className="p-4 space-y-4">
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

const sourceColumns: LemonTableColumns<ManagedWarehouseSourceTableStatusApi> = [
    {
        title: 'Source',
        key: 'source',
        render: (_, table) => (
            <div>
                <div className="font-medium">{table.source_name}</div>
                <div className="text-xs text-muted">{table.source_type}</div>
            </div>
        ),
    },
    {
        title: 'Table',
        dataIndex: 'table_name',
        render: (tableName) => <code>{tableName}</code>,
    },
    {
        title: 'Warehouse status',
        key: 'readiness_state',
        render: (_, table) => (
            <div className="space-y-1 max-w-96">
                <StatusTag readinessState={table.readiness_state} />
                <div className="text-xs text-muted">{table.detail}</div>
            </div>
        ),
    },
    {
        title: 'Backfill',
        key: 'backfill',
        render: (_, table) =>
            table.total_chunks ? `${table.completed_chunks} / ${table.total_chunks} chunks` : 'No active backfill',
    },
    {
        title: 'Pending imports',
        dataIndex: 'pending_batches',
        render: (pendingBatches) =>
            typeof pendingBatches === 'number' ? pendingBatches.toLocaleString() : 'Unavailable',
    },
    {
        title: 'Last source import',
        dataIndex: 'last_synced_at',
        render: (lastSyncedAt) =>
            typeof lastSyncedAt === 'string' ? humanFriendlyDetailedTime(lastSyncedAt) : 'Not synced yet',
    },
]

export function OverviewTab(): JSX.Element {
    const { managedWarehouseDataStatus, managedWarehouseDataStatusLoading } = useValues(managedWarehouseDataStatusLogic)
    const { loadManagedWarehouseDataStatus } = useActions(managedWarehouseDataStatusLogic)

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

            <LemonCard className="p-0 overflow-hidden">
                <div className="p-4 flex items-start justify-between gap-3 border-b">
                    <div>
                        <h3 className="mb-1">Imported source tables</h3>
                        <p className="text-muted mb-0">{managedWarehouseDataStatus.sources.detail}</p>
                    </div>
                    <StatusTag readinessState={managedWarehouseDataStatus.sources.readiness_state} />
                </div>
                {managedWarehouseDataStatus.sources.tables.length ? (
                    <LemonTable
                        embedded
                        columns={sourceColumns}
                        dataSource={managedWarehouseDataStatus.sources.tables}
                        rowKey="schema_id"
                        pagination={{ pageSize: 20 }}
                    />
                ) : (
                    <div className="p-6 text-muted">No imported source tables are configured for this warehouse.</div>
                )}
            </LemonCard>
        </div>
    )
}
