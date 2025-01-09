import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { Experiment } from '~/types'

import { experimentLogic, getDefaultFunnelsMetric } from '../experimentLogic'

export function MetricSourceModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const { experiment, isPrimaryMetricSourceModalOpen, isSecondaryMetricSourceModalOpen } = useValues(
        experimentLogic({ experimentId })
    )
    const {
        setExperiment,
        closePrimaryMetricSourceModal,
        closeSecondaryMetricSourceModal,
        openPrimaryMetricModal,
        openPrimarySharedMetricModal,
        openSecondaryMetricModal,
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
                    className="flex-1 cursor-pointer p-4 rounded border hover:border-primary-3000"
                    onClick={() => {
                        closeCurrentModal()

                        const newMetrics = [...experiment[metricsField], getDefaultFunnelsMetric()]
                        setExperiment({
                            [metricsField]: newMetrics,
                        })
                        openMetricModal(newMetrics.length - 1)
                    }}
                >
                    <div className="font-semibold">
                        <span>Single-use</span>
                    </div>
                    <div className="text-muted text-sm leading-relaxed">
                        Create a new metric specific to this experiment.
                    </div>
                </div>
                <div
                    className="flex-1 cursor-pointer p-4 rounded border hover:border-primary-3000"
                    onClick={() => {
                        closeCurrentModal()
                        openSharedMetricModal(null)
                    }}
                >
                    <div className="font-semibold">
                        <span>Shared</span>
                    </div>
                    <div className="text-muted text-sm leading-relaxed">
                        Use a pre-configured metric that can be reused across experiments.
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
