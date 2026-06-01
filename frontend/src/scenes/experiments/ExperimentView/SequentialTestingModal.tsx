import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import {
    DEFAULT_SEQUENTIAL_TUNING_PARAMETER,
    MAX_SEQUENTIAL_TUNING_PARAMETER,
    SequentialSelection,
    getSequentialSelection,
    resolveSequentialTuningParameter,
} from './sequential'

export function SequentialTestingModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperimentSettings, setExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)
    const { closeSequentialTestingModal } = useActions(modalsLogic)
    const { isSequentialTestingModalOpen } = useValues(modalsLogic)

    const selection = getSequentialSelection(experiment.stats_config?.frequentist)
    const teamDefaultEnabled = experimentsConfig?.default_sequential_testing_enabled ?? false
    const teamDefaultTuningParameter = experimentsConfig?.default_sequential_tuning_parameter ?? null
    const tuningParameter = resolveSequentialTuningParameter(
        experiment.stats_config?.frequentist,
        teamDefaultTuningParameter,
        DEFAULT_SEQUENTIAL_TUNING_PARAMETER
    )

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        closeSequentialTestingModal()
    }

    const updateSelection = (next: SequentialSelection): void => {
        const existingFrequentist = experiment.stats_config?.frequentist ?? {}
        if (next === 'default') {
            // Drop the sequential keys entirely so the team default applies at evaluation time.
            const {
                sequential_testing_enabled: _enabled,
                sequential_tuning_parameter: _param,
                ...restFrequentist
            } = existingFrequentist
            setExperiment({
                stats_config: {
                    ...experiment.stats_config,
                    frequentist: restFrequentist,
                },
            })
            return
        }
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                frequentist: {
                    ...existingFrequentist,
                    sequential_testing_enabled: next === 'enabled',
                },
            },
        })
    }

    const updateTuningParameter = (sequential_tuning_parameter: number): void => {
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                frequentist: {
                    ...experiment.stats_config?.frequentist,
                    sequential_tuning_parameter,
                },
            },
        })
    }

    const onSave = (): void => {
        updateExperimentSettings({ stats_config: experiment.stats_config })
        closeSequentialTestingModal()
    }

    return (
        <LemonModal
            maxWidth={600}
            isOpen={isSequentialTestingModalOpen}
            onClose={onClose}
            title="Sequential testing"
            footer={
                <div className="flex items-center gap-2 justify-end">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={onSave}>
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <p className="text-secondary m-0">
                    Sequential testing produces always-valid p-values that are robust to peeking. You can check the
                    experiment as often as you want without inflating the false positive rate, at the cost of slightly
                    wider confidence intervals. Only applies to frequentist analyses.
                </p>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Sequential testing</LemonLabel>
                    <LemonSelect<SequentialSelection>
                        value={selection}
                        onChange={updateSelection}
                        options={[
                            {
                                value: 'default',
                                label: `Use team default (${teamDefaultEnabled ? 'Enabled' : 'Disabled'})`,
                            },
                            { value: 'enabled', label: 'Enabled' },
                            { value: 'disabled', label: 'Disabled' },
                        ]}
                    />
                </div>
                {selection === 'enabled' && (
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Tuning parameter</LemonLabel>
                        <LemonInput
                            type="number"
                            min={1}
                            max={MAX_SEQUENTIAL_TUNING_PARAMETER}
                            value={tuningParameter}
                            onChange={(value) => {
                                if (
                                    typeof value !== 'number' ||
                                    !Number.isFinite(value) ||
                                    value < 1 ||
                                    value > MAX_SEQUENTIAL_TUNING_PARAMETER
                                ) {
                                    return
                                }
                                updateTuningParameter(Math.round(value))
                            }}
                            className="w-32"
                        />
                        <p className="text-xs text-secondary m-0">
                            Roughly the sample size at which the confidence sequence is tightest. Set close to the
                            expected total sample size of the experiment. Default is{' '}
                            {DEFAULT_SEQUENTIAL_TUNING_PARAMETER}.
                        </p>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
