import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonModal, Link } from '@posthog/lemon-ui'

import { experimentLogic } from '../experimentLogic'
import { experimentMetricModalLogic } from './experimentMetricModalLogic'
import { metricSourceModalLogic } from './metricSourceModalLogic'
import { sharedMetricModalLogic } from './sharedMetricModalLogic'

const METRIC_COUNT_WARNING_THRESHOLD = 3

export const MetricSourceModal = (): JSX.Element | null => {
    const { isModalOpen, context } = useValues(metricSourceModalLogic)
    const { closeMetricSourceModal } = useActions(metricSourceModalLogic)

    const { openExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { openSharedMetricModal } = useActions(sharedMetricModalLogic)

    const { experiment } = useValues(experimentLogic)

    const metricCount =
        context.field === 'metrics' ? (experiment.metrics?.length ?? 0) : (experiment.metrics_secondary?.length ?? 0)

    const isRunning = !!experiment.start_date
    const showWarning = metricCount >= METRIC_COUNT_WARNING_THRESHOLD || isRunning

    return (
        <LemonModal isOpen={isModalOpen} onClose={closeMetricSourceModal} width={1000} title="Choose metric source">
            <div className="flex gap-4 mb-4">
                <div
                    className="flex-1 cursor-pointer p-4 rounded border hover:border-accent"
                    onClick={() => {
                        closeMetricSourceModal()
                        openExperimentMetricModal(context)
                    }}
                >
                    <div className="font-semibold">
                        <span>Single-use</span>
                    </div>
                    <div className="text-secondary text-sm leading-relaxed">
                        Create a new metric specific to this experiment.
                    </div>
                </div>
                <div
                    className="flex-1 cursor-pointer p-4 rounded border hover:border-accent"
                    onClick={() => {
                        closeMetricSourceModal()
                        openSharedMetricModal(context)
                    }}
                >
                    <div className="font-semibold">
                        <span>Shared</span>
                    </div>
                    <div className="text-secondary text-sm leading-relaxed">
                        Use a pre-configured metric that can be reused across experiments.
                    </div>
                </div>
            </div>
            {showWarning && (
                <div className="flex items-center gap-2 p-3 rounded bg-warning-highlight text-sm">
                    <IconWarning className="text-warning text-lg shrink-0" />
                    <p className="mb-0">
                        {isRunning && metricCount >= METRIC_COUNT_WARNING_THRESHOLD
                            ? 'This experiment is already running and has several metrics. Choosing what to measure after seeing data can bias your results. '
                            : isRunning
                              ? 'This experiment is already running. Choosing what to measure after seeing data can bias your results. '
                              : 'Each additional metric is another result to interpret. Make sure each has a clear hypothesis. '}
                        <Link to="https://posthog.com/docs/experiments/best-practices" target="_blank">
                            Learn more
                        </Link>
                    </p>
                </div>
            )}
        </LemonModal>
    )
}
