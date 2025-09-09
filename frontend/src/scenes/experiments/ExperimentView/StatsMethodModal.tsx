import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'

import { ExperimentStatsMethod } from '~/types'

import { SelectableCard } from '../components/SelectableCard'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

export function StatsMethodModal(): JSX.Element {
    const { experiment, statsMethod } = useValues(experimentLogic)
    const { updateExperiment, setExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeStatsEngineModal } = useActions(modalsLogic)
    const { isStatsEngineModalOpen } = useValues(modalsLogic)

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        closeStatsEngineModal()
    }

    return (
        <LemonModal
            maxWidth={600}
            isOpen={isStatsEngineModalOpen}
            onClose={onClose}
            title="Change stats engine"
            footer={
                <div className="flex items-center gap-2 justify-end">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            updateExperiment({ stats_config: experiment.stats_config })
                            closeStatsEngineModal()
                        }}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex gap-4 mb-4">
                <SelectableCard
                    title="Bayesian"
                    description="This approach gives you a probability-based view of results, showing how likely one variant is to be better than another, based on the observed data."
                    selected={statsMethod === ExperimentStatsMethod.Bayesian}
                    onClick={() => {
                        setExperiment({
                            stats_config: {
                                ...experiment.stats_config,
                                method: ExperimentStatsMethod.Bayesian,
                            },
                        })
                    }}
                />
                <SelectableCard
                    title="Frequentist"
                    description="This approach uses statistical tests to determine whether observed differences are significant. It's based on p-values and is widely used in traditional A/B testing and scientific research."
                    selected={statsMethod === ExperimentStatsMethod.Frequentist}
                    onClick={() => {
                        setExperiment({
                            stats_config: {
                                ...experiment.stats_config,
                                method: ExperimentStatsMethod.Frequentist,
                            },
                        })
                    }}
                />
            </div>
        </LemonModal>
    )
}
