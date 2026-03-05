import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { ExperimentStatsMethod } from '~/types'

import { StatsMethodSelector } from '../components/StatsMethodSelector'
import { CONFIDENCE_LEVEL_OPTIONS } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { DistributionTable } from './DistributionTable'
import { ExperimentDuration } from './ExperimentDuration'
import { ReleaseConditionsTable } from './ReleaseConditionsTable'

export function SetupTab(): JSX.Element {
    const { experiment, statsMethod, isExperimentDraft } = useValues(experimentLogic)
    const { updateExperiment, setExperiment } = useActions(experimentLogic)

    const isBayesian = statsMethod === ExperimentStatsMethod.Bayesian

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
        <div className="flex flex-col gap-8">
            {!isExperimentDraft && (
                <div>
                    <ExperimentDuration />
                </div>
            )}
            <ReleaseConditionsTable />
            <DistributionTable />
            <div className="flex flex-col max-w-[800px]">
                <h2 className="font-semibold text-lg">Statistics</h2>
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
                <div className="flex flex-col mt-6">
                    <h2 className="font-semibold text-lg">Confidence level</h2>
                    <LemonSelect
                        value={currentConfidenceLevel}
                        onChange={handleConfidenceLevelChange}
                        options={CONFIDENCE_LEVEL_OPTIONS}
                        className="w-24"
                    />
                    <p className="text-xs text-secondary m-0 mt-2">
                        {isBayesian
                            ? `At ${currentConfidenceLevel * 100}%, we require a variant to have a ${currentConfidenceLevel * 100}% or higher chance of being better before calling it a winner.`
                            : `Higher confidence means we need stronger evidence before declaring a winner. ${currentConfidenceLevel * 100}% confidence requires a p-value below ${(1 - currentConfidenceLevel).toFixed(2)}.`}
                    </p>
                </div>
                <div className="mt-6">
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            updateExperiment({ stats_config: experiment.stats_config })
                        }}
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
