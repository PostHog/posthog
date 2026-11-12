import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { approveDisabledReason, bulkBusyReason, deleteDisabledReason } from '../metricActionGuards'
import { metricsLogic } from '../metricsLogic'
import { ConfirmDeleteMetricsDialog } from './ConfirmDeleteMetricsDialog'

export function CatalogMetricRowMenu({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    const { actionsInFlight, bulkActionInFlight } = useValues(metricsLogic)
    const { approveMetric, refreshMetricFromInsight, deleteMetric } = useActions(metricsLogic)
    const [confirmingDelete, setConfirmingDelete] = useState(false)
    const inFlight = !!actionsInFlight[metric.name]

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            size="icon"
                            aria-label={`More actions for ${metric.name}`}
                            className="text-muted-foreground"
                            loading={inFlight}
                            data-attr="data-catalog-metrics-row-actions"
                        />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-48">
                    {metric.status !== 'approved' && (
                        <DropdownMenuItem
                            onClick={() => approveMetric(metric.name)}
                            disabledReason={approveDisabledReason(metric, bulkActionInFlight)}
                            data-attr="data-catalog-metrics-approve"
                        >
                            Approve
                        </DropdownMenuItem>
                    )}
                    {metric.source_insight_short_id && (
                        <DropdownMenuItem
                            onClick={() => refreshMetricFromInsight(metric.name)}
                            disabledReason={bulkBusyReason(bulkActionInFlight)}
                            data-attr="data-catalog-metrics-refresh-from-insight"
                        >
                            Refresh from insight
                        </DropdownMenuItem>
                    )}
                    {(metric.status !== 'approved' || metric.source_insight_short_id) && <DropdownMenuSeparator />}
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={() => setConfirmingDelete(true)}
                        disabledReason={deleteDisabledReason(inFlight, bulkActionInFlight)}
                        data-attr="data-catalog-metrics-delete"
                    >
                        Delete
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <ConfirmDeleteMetricsDialog
                open={confirmingDelete}
                title="Delete metric?"
                description={`This deletes ${metric.name} and makes its name available for a new metric. Queries and links that reference it will stop working.`}
                onClose={() => setConfirmingDelete(false)}
                onConfirm={() => deleteMetric(metric.name)}
                dataAttr="data-catalog-metrics-delete-confirm"
            />
        </>
    )
}
