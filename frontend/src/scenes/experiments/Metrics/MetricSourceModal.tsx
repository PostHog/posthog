import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { getDefaultBinomialMetric, getDefaultFunnelsMetric } from '../utils'

export function MetricSourceModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const { experiment, isPrimaryMetricSourceModalOpen, isSecondaryMetricSourceModalOpen, shouldUseExperimentMetrics } =
        useValues(experimentLogic({ experimentId }))
    const {
        setExperiment,
        closePrimaryMetricSourceModal,
        closeSecondaryMetricSourceModal,
        openPrimaryMetricModal,
        openSecondaryMetricModal,
        openPrimarySharedMetricModal,
        openSecondarySharedMetricModal,
    } = useActions(experimentLogic({ experimentId }))

    const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'
    const isOpen = isSecondary ? isSecondaryMetricSourceModalOpen : isPrimaryMetricSourceModalOpen
    const closeCurrentModal = isSecondary ? closeSecondaryMetricSourceModal : closePrimaryMetricSourceModal
    const openMetricModal = isSecondary ? openSecondaryMetricModal : openPrimaryMetricModal
    const openSharedMetricModal = isSecondary ? openSecondarySharedMetricModal : openPrimarySharedMetricModal

    return (
        <LemonModal isOpen={isOpen} onClose={closeCurrentModal} width={1000} title="Choose metric source">
            <div className="flex gap-4 mb-4">
                <div
                    className="flex-1 cursor-pointer p-4 rounded border hover:border-accent-primary"
                    onClick={() => {
                        closeCurrentModal()

                        const defaultMetric = shouldUseExperimentMetrics
                            ? getDefaultBinomialMetric()
                            : getDefaultFunnelsMetric()
                        const newMetrics = [...experiment[metricsField], defaultMetric]
                        setExperiment({
                            [metricsField]: newMetrics,
                        })
                        openMetricModal(newMetrics.length - 1)
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
                    className="flex-1 cursor-pointer p-4 rounded border hover:border-accent-primary"
                    onClick={() => {
                        closeCurrentModal()
                        openSharedMetricModal(null)
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
        </LemonModal>
    )
}
