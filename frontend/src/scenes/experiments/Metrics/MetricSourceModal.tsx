import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { modalsLogic } from '../modalsLogic'
import { METRIC_CONTEXTS, experimentMetricModalLogic } from './experimentMetricModalLogic'

export function MetricSourceModal({ isSecondary }: { isSecondary?: boolean }): JSX.Element {
    const {
        closePrimaryMetricSourceModal,
        closeSecondaryMetricSourceModal,
        openPrimarySharedMetricModal,
        openSecondarySharedMetricModal,
    } = useActions(modalsLogic)
    const { isPrimaryMetricSourceModalOpen, isSecondaryMetricSourceModalOpen } = useValues(modalsLogic)

    const isOpen = isSecondary ? isSecondaryMetricSourceModalOpen : isPrimaryMetricSourceModalOpen
    const closeCurrentModal = isSecondary ? closeSecondaryMetricSourceModal : closePrimaryMetricSourceModal
    const openSharedMetricModal = isSecondary ? openSecondarySharedMetricModal : openPrimarySharedMetricModal

    const { openExperimentMetricModal } = useActions(experimentMetricModalLogic)

    return (
        <LemonModal isOpen={isOpen} onClose={closeCurrentModal} width={1000} title="Choose metric source">
            <div className="flex gap-4 mb-4">
                <div
                    className="flex-1 cursor-pointer p-4 rounded border hover:border-accent"
                    onClick={() => {
                        closeCurrentModal()
                        openExperimentMetricModal(METRIC_CONTEXTS[isSecondary ? 'secondary' : 'primary'])
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
