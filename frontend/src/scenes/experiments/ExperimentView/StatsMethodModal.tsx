import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'

import { ExperimentStatsMethod } from '~/types'

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
                <div className="flex items-center justify-end gap-2">
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
            <div className="mb-4 flex gap-4">
                <LemonButton
                    className={`trends-metric-form__exposure-button flex-1 cursor-pointer rounded border p-4 ${
                        statsMethod === ExperimentStatsMethod.Bayesian
                            ? 'border-accent bg-accent-highlight-secondary'
                            : 'border-primary'
                    }`}
                    onClick={() => {
                        setExperiment({
                            stats_config: {
                                ...experiment.stats_config,
                                method: ExperimentStatsMethod.Bayesian,
                            },
                        })
                    }}
                >
                    <div className="flex items-center justify-between font-semibold">
                        <span>Bayesian</span>
                        {statsMethod === ExperimentStatsMethod.Bayesian && (
                            <IconCheckCircle fontSize={18} color="var(--accent)" />
                        )}
                    </div>
                    <div className="text-secondary mt-1 text-sm leading-relaxed">
                        This approach gives you a probability-based view of results, showing how likely one variant is
                        to be better than another, based on the observed data.
                    </div>
                </LemonButton>
                <LemonButton
                    className={`trends-metric-form__exposure-button flex-1 cursor-pointer rounded border p-4 ${
                        statsMethod === ExperimentStatsMethod.Frequentist
                            ? 'border-accent bg-accent-highlight-secondary'
                            : 'border-primary'
                    }`}
                    onClick={() => {
                        setExperiment({
                            stats_config: {
                                ...experiment.stats_config,
                                method: ExperimentStatsMethod.Frequentist,
                            },
                        })
                    }}
                >
                    <div className="flex items-center justify-between font-semibold">
                        <span>Frequentist</span>
                        {statsMethod === ExperimentStatsMethod.Frequentist && (
                            <IconCheckCircle fontSize={18} color="var(--accent)" />
                        )}
                    </div>
                    <div className="text-secondary mt-1 text-sm leading-relaxed">
                        This approach uses statistical tests to determine whether observed differences are significant.
                        It's based on p-values and is widely used in traditional A/B testing and scientific research.
                    </div>
                </LemonButton>
            </div>
        </LemonModal>
    )
}
