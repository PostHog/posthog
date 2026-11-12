import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { approveDisabledReason } from '../metricActionGuards'
import { metricsLogic } from '../metricsLogic'
import { CatalogReviewAccess } from '../tables/CatalogReviewAccess'

export function MetricApproveButton({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    const { actionsInFlight, bulkActionInFlight } = useValues(metricsLogic)
    const { approveMetric } = useActions(metricsLogic)
    const approving = !!actionsInFlight[metric.name]

    return (
        <CatalogReviewAccess>
            <Button
                variant="outline"
                size="xs"
                loading={approving}
                disabledReason={approving ? undefined : approveDisabledReason(metric, bulkActionInFlight)}
                onClick={() => approveMetric(metric.name, 'inline')}
                data-attr="data-catalog-metrics-inline-approve"
            >
                Approve
            </Button>
        </CatalogReviewAccess>
    )
}
