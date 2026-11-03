import { METRIC_BULK_MAX } from './common'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import type { BulkMetricAction } from './metricsLogic'

const OVER_CAP_REASON = `Select at most ${METRIC_BULK_MAX} metrics at a time`
const WORKING_REASON = 'Working'

export interface MetricSelection {
    selectedNames: string[]
    approvableNames: string[]
}

export function isApprovable(metric: DataCatalogMetricApi): boolean {
    return metric.status !== 'approved' && !metric.is_drifted
}

export function bulkBusyReason(bulkActionInFlight: BulkMetricAction | null): string | undefined {
    return bulkActionInFlight ? 'A bulk action is running' : undefined
}

// Reload replaces the whole list and takes no breakpoint, so a load that resolves after a
// mutation would repaint pre-mutation rows (e.g. bring back rows a bulk delete just removed).
// Block it while any mutation is in flight; the view is authoritative again on the next load.
export function reloadDisabledReason(
    bulkActionInFlight: BulkMetricAction | null,
    actionsInFlight: Record<string, boolean>
): string | undefined {
    return (
        bulkBusyReason(bulkActionInFlight) ??
        (Object.values(actionsInFlight).some(Boolean) ? 'A metric action is running' : undefined)
    )
}

function otherBulkActionReason(
    bulkActionInFlight: BulkMetricAction | null,
    self: BulkMetricAction
): string | undefined {
    return bulkActionInFlight && bulkActionInFlight !== self ? 'Another bulk action is running' : undefined
}

export function bulkApproveDisabledReason(
    approvableCount: number,
    bulkActionInFlight: BulkMetricAction | null
): string | undefined {
    if (approvableCount === 0) {
        return 'Every selected metric is already approved or has drifted. Refresh a drifted metric first.'
    }
    if (approvableCount > METRIC_BULK_MAX) {
        return OVER_CAP_REASON
    }
    return otherBulkActionReason(bulkActionInFlight, 'approve')
}

export function bulkSelectionDisabledReason(
    selectedCount: number,
    self: BulkMetricAction,
    bulkActionInFlight: BulkMetricAction | null
): string | undefined {
    if (selectedCount === 0) {
        return 'The selected metrics are no longer available. Reload the list.'
    }
    if (selectedCount > METRIC_BULK_MAX) {
        return OVER_CAP_REASON
    }
    return otherBulkActionReason(bulkActionInFlight, self)
}

export function approveDisabledReason(
    metric: DataCatalogMetricApi,
    bulkActionInFlight: BulkMetricAction | null
): string | undefined {
    return (
        bulkBusyReason(bulkActionInFlight) ??
        (metric.is_drifted ? 'This metric has drifted from its source insight. Refresh it first.' : undefined)
    )
}

export function deleteDisabledReason(
    inFlight: boolean,
    bulkActionInFlight: BulkMetricAction | null
): string | undefined {
    return bulkBusyReason(bulkActionInFlight) ?? (inFlight ? WORKING_REASON : undefined)
}

export function resolveMetricSelection(
    allMetrics: DataCatalogMetricApi[],
    selectedIds: readonly string[]
): MetricSelection {
    const selected = new Set(selectedIds)
    const selectedMetrics = allMetrics.filter((metric) => selected.has(metric.id))
    return {
        selectedNames: selectedMetrics.map((metric) => metric.name),
        approvableNames: selectedMetrics.filter(isApprovable).map((metric) => metric.name),
    }
}
