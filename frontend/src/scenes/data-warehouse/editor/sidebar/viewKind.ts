import { DataModelingSyncInterval } from '~/types'

import { CADENCE_LABELS } from '../../saved_queries/SyncFrequencySelect'

/**
 * The text badge a sidebar row shows after its name. Saved views and materialized views have none: their
 * icon carries the kind, and a badge would take space from the name. Rows nested under a table are the
 * exception, because they have no kind icon.
 */
export function getTableKindLabel(record: Record<string, any> | undefined): string | null {
    if (!record) {
        return null
    }

    switch (record.traversedFieldType ?? record.type) {
        case 'lazy-table':
            return 'join'
        case 'virtual-table':
            return 'virtual table'
        case 'materialized_view':
            return 'materialized view'
        case 'managed-view':
            return 'managed view'
        case 'endpoint':
            return 'materialized endpoint'
        case 'view':
        case 'view-table':
            return record.type === 'view-table' ? 'view' : null
        case 'table': {
            switch (record.table?.type) {
                case 'batch_export':
                    return 'batch export'
                default:
                    return null
            }
        }
        default:
            return null
    }
}

// `sync_frequency` is the declared target. A downstream view can make the scheduler refresh sooner, so the
// tooltip says "set to" instead of claiming the effective cadence.
export function getMaterializedViewTooltip(syncFrequency: string | undefined): string {
    const cadence = syncFrequency ? CADENCE_LABELS[syncFrequency as DataModelingSyncInterval] : undefined
    return cadence ? `Materialized view - set to refresh every ${cadence}` : 'Materialized view'
}
