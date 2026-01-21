import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'

import { ExperimentStatsMethod } from '~/types'

import { StatsMethodSelector } from '../components/StatsMethodSelector'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

const CONFIDENCE_LEVEL_OPTIONS = [
    { value: 0.9, label: '90%' },
    { value: 0.95, label: '95%' },
    { value: 0.99, label: '99%' },
]

export function StatsMethodModal(): JSX.Element {
    const { experiment, statsMethod } = useValues(experimentLogic)
    const { updateExperiment, setExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeStatsEngineModal } = useActions(modalsLogic)
    const { isStatsEngineModalOpen } = useValues(modalsLogic)

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        closeStatsEngineModal()
    }

    const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian

    // For Bayesian: ci_level (default 0.95)
    // For Frequentist: confidence = 1 - alpha (default alpha 0.05 = 95% confidence)
    const currentConfidenceLevel = isBayesian
        ? (experiment.stats_config?.bayesian?.ci_level ?? 0.95)
        : 1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)

    const handleConfidenceLevelChange = (value: number): void => {
        if (isBayesian) {
            setExperiment({
                stats_config: {
                    ...experiment.stats_config,
                    bayesian: {
                        ...experiment.stats_config?.bayesian,
                        ci_level: value,
                    },
                },
            })
        } else {
            setExperiment({
                stats_config: {
                    ...experiment.stats_config,
                    frequentist: {
                        ...experiment.stats_config?.frequentist,
                        alpha: 1 - value,
                    },
                },
            })
        }
    }

    return (
        <LemonModal
            maxWidth={600}
            isOpen={isStatsEngineModalOpen}
            onClose={onClose}
            title="Statistics configuration"
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
            <div className="mb-4">
                <StatsMethodSelector
                    value={statsMethod}
                    onChange={(newStatsMethod) => {
                        setExperiment({
                            stats_config: {
                                ...experiment.stats_config,
                                method: newStatsMethod,
                            },
                        })
                    }}
                />
            </div>
            <div className="flex flex-col gap-2">
                <LemonLabel>Confidence level</LemonLabel>
                <LemonSelect
                    value={currentConfidenceLevel}
                    onChange={handleConfidenceLevelChange}
                    options={CONFIDENCE_LEVEL_OPTIONS}
                    className="w-24"
                />
                <p className="text-xs text-secondary m-0">
                    {isBayesian
                        ? `At ${currentConfidenceLevel * 100}%, we require a variant to have a ${currentConfidenceLevel * 100}% or higher chance of being better before calling it a winner.`
                        : `Higher confidence means we need stronger evidence before declaring a winner. ${currentConfidenceLevel * 100}% confidence requires a p-value below ${(1 - currentConfidenceLevel).toFixed(2)}.`}
                </p>
            </div>
        </LemonModal>
    )
}
