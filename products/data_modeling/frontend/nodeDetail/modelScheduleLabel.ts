import { CADENCE_LABELS, modeDisabledReason } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import type { DataModelingNodeType, DataModelingSyncInterval, DataWarehouseSavedQuery } from '~/types'

export function modelScheduleLabel({
    suspended,
    nodeType,
    savedQuery,
    savedQueryError,
}: {
    suspended: boolean
    nodeType: DataModelingNodeType
    savedQuery: DataWarehouseSavedQuery | null
    savedQueryError: boolean
}): string | null {
    if (suspended) {
        return 'Suspended after repeated failures'
    }
    if (nodeType === 'endpoint') {
        return 'Managed by endpoint'
    }
    if (modeDisabledReason(savedQuery?.sync_frequency_bounds)) {
        return 'Managed by PostHog'
    }
    if (!savedQuery) {
        return savedQueryError ? 'Schedule unavailable' : null
    }
    const cadence = savedQuery.sync_frequency
    if (!cadence || cadence === 'never') {
        return 'Paused'
    }
    return `Every ${CADENCE_LABELS[cadence as DataModelingSyncInterval] ?? cadence}`
}
