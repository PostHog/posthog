import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { modalsLogic } from '../modalsLogic'
import { experimentMetricModalLogic } from './experimentMetricModalLogic'
import { metricSourceModalLogic } from './metricSourceModalLogic'

export const MetricSourceModal = (): JSX.Element => {
    const { isModalOpen, context } = useValues(metricSourceModalLogic)
    const { closeMetricSourceModal } = useActions(metricSourceModalLogic)

    const { openExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { openPrimarySharedMetricModal, openSecondarySharedMetricModal } = useActions(modalsLogic)

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
                        context.type === 'primary'
                            ? openPrimarySharedMetricModal(null)
                            : openSecondarySharedMetricModal(null)
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
