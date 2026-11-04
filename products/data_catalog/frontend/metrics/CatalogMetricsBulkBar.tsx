import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Button } from '@posthog/quill'

import { metricCount } from '../common'
import { CatalogBulkBar } from '../components/CatalogBulkBar'
import { bulkApproveDisabledReason, bulkSelectionDisabledReason, resolveMetricSelection } from '../metricActionGuards'
import { metricsLogic } from '../metricsLogic'
import { catalogMetricsLogic } from './catalogMetricsLogic'
import { ConfirmDeleteMetricsDialog } from './ConfirmDeleteMetricsDialog'
import { MetricOwnerCombobox } from './MetricOwnerCombobox'

export function CatalogMetricsBulkBar(): JSX.Element {
    const { allMetrics, bulkActionInFlight } = useValues(metricsLogic)
    const { bulkApproveMetrics, bulkDeleteMetrics, bulkChangeMetricOwner } = useActions(metricsLogic)
    const { selectedMetricIds } = useValues(catalogMetricsLogic)
    const { clearMetricSelection } = useActions(catalogMetricsLogic)
    const [confirmingDelete, setConfirmingDelete] = useState(false)
    const { selectedNames, approvableNames } = resolveMetricSelection(allMetrics, selectedMetricIds)

    return (
        <CatalogBulkBar
            selectedLabel={`${metricCount(selectedMetricIds.length)} selected`}
            onClear={clearMetricSelection}
            dataAttr="data-catalog-metrics-bulk-bar"
        >
            <Button
                variant="outline"
                size="sm"
                loading={bulkActionInFlight === 'approve'}
                disabledReason={bulkApproveDisabledReason(approvableNames.length, bulkActionInFlight)}
                onClick={() => bulkApproveMetrics(approvableNames, clearMetricSelection)}
                data-attr="data-catalog-metrics-bulk-approve"
            >
                Approve ({approvableNames.length})
            </Button>
            <MetricOwnerCombobox
                label="Change owner"
                variant="outline"
                loading={bulkActionInFlight === 'change_owner'}
                disabledReason={bulkSelectionDisabledReason(selectedNames.length, 'change_owner', bulkActionInFlight)}
                onChange={(owner) => bulkChangeMetricOwner(selectedNames, owner, clearMetricSelection)}
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
            <ConfirmDeleteMetricsDialog
                open={confirmingDelete}
                title={`Delete ${metricCount(selectedNames.length)}?`}
                description="This deletes the selected metrics and makes their names available for new metrics. Queries and links that reference them will stop working."
                onClose={() => setConfirmingDelete(false)}
                onConfirm={() => bulkDeleteMetrics(selectedNames, clearMetricSelection)}
                dataAttr="data-catalog-metrics-bulk-delete-confirm"
            />
        </CatalogBulkBar>
    )
}
