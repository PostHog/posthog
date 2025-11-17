import { useActions } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import type { MetricContext } from '~/scenes/experiments/Metrics/experimentMetricModalLogic'
import { experimentMetricModalLogic } from '~/scenes/experiments/Metrics/experimentMetricModalLogic'
import { getDefaultMetricTitle, getMetricTag } from '~/scenes/experiments/MetricsView/shared/utils'

import { MetricConversionWindow } from './MetricConversionWindow'
import { MetricEventDetails } from './MetricEventDetails'
import { MetricGoal } from './MetricGoal'
import { MetricOutlierHandling } from './MetricOutlierHandling'
import { MetricRecentActivity } from './MetricRecentActivity'
import { MetricStepOrder } from './MetricStepOrder'

export type MetricCardProps = {
    metric: ExperimentMetric
    metricContext: MetricContext
    onDelete: (metric: ExperimentMetric, context: MetricContext) => void
    filterTestAccounts: boolean
}

export const MetricCard = ({ metric, metricContext, onDelete, filterTestAccounts }: MetricCardProps): JSX.Element => {
    const { openExperimentMetricModal } = useActions(experimentMetricModalLogic)

    const metricTag = getMetricTag(metric)
    const metricName = metric.name || getDefaultMetricTitle(metric)

    const handleDelete = (): void => {
        if (metric.isSharedMetric) {
            return onDelete(metric, metricContext)
        }

        LemonDialog.open({
            title: 'Delete metric?',
            description: 'Are you sure you want to delete this metric? This action cannot be undone.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => onDelete(metric, metricContext),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <div className="border rounded bg-surface-primary p-4">
            <div className="space-y-3">
                <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0 gap-2">
                        <div className="font-semibold text-sm mb-1 break-words">{metricName}</div>
                        <MetricEventDetails metric={metric} />
                        <div className="flex items-center mt-2">
                            <LemonTag type="muted" size="small">
                                {metricTag}
                            </LemonTag>
                            {metric.isSharedMetric && (
                                <LemonTag type="option" size="small">
                                    Shared metric
                                </LemonTag>
                            )}
                        </div>
                    </div>
                    <div className="flex gap-1 flex-shrink-0">
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconPencil fontSize="12" />}
                            tooltip="Edit metric"
                            onClick={() => openExperimentMetricModal(metricContext, metric)}
                        />
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconTrash fontSize="12" />}
                            tooltip="Delete metric"
                            onClick={handleDelete}
                            status="danger"
                        />
                    </div>
                </div>

                <div className="border-t border-border" />

                <div className="flex items-center justify-between">
                    <div className="space-y-1">
                        <MetricGoal metric={metric} />
                        <MetricConversionWindow metric={metric} />
                        <MetricStepOrder metric={metric} />
                        <MetricOutlierHandling metric={metric} />
                    </div>

                    <MetricRecentActivity metric={metric} filterTestAccounts={filterTestAccounts} />
                </div>
            </div>
        </div>
    )
}
