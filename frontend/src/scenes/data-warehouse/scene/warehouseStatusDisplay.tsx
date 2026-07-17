import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type {
    ManagedWarehouseReadinessStateEnumApi,
    ManagedWarehouseSourceTableStatusApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

// Shared between the Overview tab's dataset/source cards and the per-source schema modal, so a
// readiness state reads and ranks identically everywhere it appears.

export const STATUS_LABELS: Record<ManagedWarehouseReadinessStateEnumApi, string> = {
    not_configured: 'Not configured',
    waiting: 'Waiting',
    backfilling: 'Backfilling',
    catching_up: 'Catching up',
    up_to_date: 'Up to date',
    needs_attention: 'Needs attention',
    unknown: 'Status unavailable',
    sync_paused: 'Sync paused',
}

export const STATUS_TAG_TYPES: Record<ManagedWarehouseReadinessStateEnumApi, LemonTagType> = {
    not_configured: 'muted',
    waiting: 'warning',
    backfilling: 'primary',
    catching_up: 'primary',
    up_to_date: 'success',
    needs_attention: 'danger',
    unknown: 'muted',
    sync_paused: 'default',
}

// Most severe first, matching the order the API returns sources/tables in.
export const STATUS_SEVERITY: Record<ManagedWarehouseReadinessStateEnumApi, number> = {
    needs_attention: 0,
    backfilling: 1,
    catching_up: 2,
    waiting: 3,
    unknown: 4,
    sync_paused: 5,
    up_to_date: 6,
    not_configured: 7,
}

export function StatusTag({ readinessState }: { readinessState: ManagedWarehouseReadinessStateEnumApi }): JSX.Element {
    return <LemonTag type={STATUS_TAG_TYPES[readinessState]}>{STATUS_LABELS[readinessState]}</LemonTag>
}

// Per-schema detail columns: used by the drill-down modal, scoped to one source's schemas.
export const sourceSchemaColumns: LemonTableColumns<ManagedWarehouseSourceTableStatusApi> = [
    {
        title: 'Table',
        dataIndex: 'table_name',
        render: (tableName) => <code>{tableName}</code>,
        sorter: (a, b) => a.table_name.localeCompare(b.table_name),
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
        sorter: (a, b) => STATUS_SEVERITY[a.readiness_state] - STATUS_SEVERITY[b.readiness_state],
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
        // Unavailable counts sort last rather than as zero, which would read as "nothing pending".
        sorter: (a, b) => (a.pending_batches ?? -1) - (b.pending_batches ?? -1),
    },
    {
        title: 'Last source import',
        dataIndex: 'last_synced_at',
        render: (lastSyncedAt) =>
            typeof lastSyncedAt === 'string' ? humanFriendlyDetailedTime(lastSyncedAt) : 'Not synced yet',
        sorter: (a, b) => new Date(a.last_synced_at ?? 0).getTime() - new Date(b.last_synced_at ?? 0).getTime(),
    },
]
