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
                    description="Gives you a clear win probability, showing how likely one variant is to be better than another. Great for product engineers new to experimentation."
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
                    description="Uses p-values to determine statistical significance. Often preferred by data scientists and teams experienced with traditional A/B testing."
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
