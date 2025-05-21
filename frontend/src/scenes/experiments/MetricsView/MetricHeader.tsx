import { IconCopy, IconPencil } from '@posthog/icons'
import { useActions } from 'kea'
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
        duplicateMetric,
    } = useActions(experimentLogic)

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
                                // Use our new dedicated action for duplicating metrics
                                // This avoids updating the entire experiment
                                duplicateMetric(metric, isPrimaryMetric)
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
