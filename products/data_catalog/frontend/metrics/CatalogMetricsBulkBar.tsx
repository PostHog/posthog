import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Button, Text } from '@posthog/quill'

import { metricCount } from '../common'
import { bulkApproveDisabledReason, bulkSelectionDisabledReason, resolveMetricSelection } from '../metricActionGuards'
import { metricsLogic } from '../metricsLogic'
import { ConfirmDeleteMetricsDialog } from './ConfirmDeleteMetricsDialog'
import { MetricOwnerCombobox } from './MetricOwnerCombobox'

interface CatalogMetricsBulkBarProps {
    selectedIds: string[]
    clearSelection: () => void
}

export function CatalogMetricsBulkBar({ selectedIds, clearSelection }: CatalogMetricsBulkBarProps): JSX.Element {
    const { allMetrics, bulkActionInFlight } = useValues(metricsLogic)
    const { bulkApproveMetrics, bulkDeleteMetrics, bulkChangeMetricOwner } = useActions(metricsLogic)
    const [confirmingDelete, setConfirmingDelete] = useState(false)
    const { selectedNames, approvableNames } = resolveMetricSelection(allMetrics, selectedIds)

    return (
        <div
            className="sticky bottom-4 z-10 flex flex-wrap items-center gap-2 self-center rounded-md border border-border bg-background px-2 py-1 shadow-md"
            data-attr="data-catalog-metrics-bulk-bar"
        >
            <Text size="xs" variant="muted" className="tabular-nums">
                {metricCount(selectedIds.length)} selected
            </Text>
            <Button
                variant="outline"
                size="sm"
                loading={bulkActionInFlight === 'approve'}
                disabledReason={bulkApproveDisabledReason(approvableNames.length, bulkActionInFlight)}
                onClick={() => bulkApproveMetrics(approvableNames, clearSelection)}
                data-attr="data-catalog-metrics-bulk-approve"
            >
                Approve ({approvableNames.length})
            </Button>
            <MetricOwnerCombobox
                label="Change owner"
                variant="outline"
                loading={bulkActionInFlight === 'change_owner'}
                disabledReason={bulkSelectionDisabledReason(selectedNames.length, 'change_owner', bulkActionInFlight)}
                onChange={(owner) => bulkChangeMetricOwner(selectedNames, owner, clearSelection)}
                dataAttr="data-catalog-metrics-bulk-change-owner"
            />
            <Button
                variant="destructive-outline"
                size="sm"
                loading={bulkActionInFlight === 'delete'}
                disabledReason={bulkSelectionDisabledReason(selectedNames.length, 'delete', bulkActionInFlight)}
                onClick={() => setConfirmingDelete(true)}
                data-attr="data-catalog-metrics-bulk-delete"
            >
                Delete
            </Button>
            <Button size="sm" onClick={clearSelection} data-attr="data-catalog-metrics-bulk-clear">
                Clear selection
            </Button>
            <ConfirmDeleteMetricsDialog
                open={confirmingDelete}
                title={`Delete ${metricCount(selectedNames.length)}?`}
                description="This deletes the selected metrics and makes their names available for new metrics. Queries and links that reference them will stop working."
                onClose={() => setConfirmingDelete(false)}
                onConfirm={() => bulkDeleteMetrics(selectedNames, clearSelection)}
                dataAttr="data-catalog-metrics-bulk-delete-confirm"
            />
        </div>
    )
}
