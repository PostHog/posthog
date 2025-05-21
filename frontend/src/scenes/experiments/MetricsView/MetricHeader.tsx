import { IconCopy, IconPencil } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { experimentLogic } from '../experimentLogic'
import { MetricTitle } from './MetricTitle'
import { getMetricTag } from './utils'

export const MetricHeader = ({
    metricIndex,
    metric,
    metricType,
    isPrimaryMetric,
}: {
    metricIndex: number
    metric: any
    metricType: any
    isPrimaryMetric: boolean
}): JSX.Element => {
    /**
     * This is a bit overkill, since primary and secondary metric dialogs are
     * identical.
     * Also, it's not the responsibility of this component to understand
     * the difference between primary and secondary metrics.
     * For this component, primary and secondary are identical,
     * except for which modal to open.
     * The openModal function has to be provided as a dependency.
     */
    const {
        openPrimaryMetricModal,
        openSecondaryMetricModal,
        openPrimarySharedMetricModal,
        openSecondarySharedMetricModal,
        updateExperiment,
    } = useActions(experimentLogic)

    const { experiment } = useValues(experimentLogic)

    return (
        <div className="text-xs font-semibold whitespace-nowrap overflow-hidden">
            <div className="deprecated-space-y-1">
                <div className="flex items-center gap-2">
                    <div className="@container cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis flex-grow flex items-start">
                        <span className="mr-1">{metricIndex + 1}.</span>
                        <MetricTitle metric={metric} metricType={metricType} />
                    </div>
                    <div className="flex gap-1">
                        <LemonButton
                            className="flex-shrink-0"
                            type="secondary"
                            size="xsmall"
                            icon={<IconCopy fontSize="12" />}
                            tooltip="Duplicate"
                            onClick={() => {
                                // Create a copy of the metric with a new name
                                const newMetric = { ...metric, id: undefined, name: `${metric.name} (copy)` }

                                // Update the experiment with the new metric
                                if (isPrimaryMetric) {
                                    updateExperiment({
                                        metrics: [...experiment.metrics, newMetric],
                                    })
                                } else {
                                    updateExperiment({
                                        metrics_secondary: [...experiment.metrics_secondary, newMetric],
                                    })
                                }
                            }}
                        />
                        <LemonButton
                            className="flex-shrink-0"
                            type="secondary"
                            size="xsmall"
                            icon={<IconPencil fontSize="12" />}
                            tooltip="Edit"
                            onClick={() => {
                                const openModal = isPrimaryMetric
                                    ? metric.isSharedMetric
                                        ? openPrimarySharedMetricModal
                                        : openPrimaryMetricModal
                                    : metric.isSharedMetric
                                    ? openSecondarySharedMetricModal
                                    : openSecondaryMetricModal

                                openModal(metric.isSharedMetric ? metric.sharedMetricId : metricIndex)
                            }}
                        />
                    </div>
                </div>
                <div className="deprecated-space-x-1">
                    <LemonTag type="muted" size="small">
                        {getMetricTag(metric)}
                    </LemonTag>
                    {metric.isSharedMetric && (
                        <LemonTag type="option" size="small">
                            Shared
                        </LemonTag>
                    )}
                </div>
            </div>
        </div>
    )
}
