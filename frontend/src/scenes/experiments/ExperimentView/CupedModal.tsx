import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import { DEFAULT_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { CupedSelection, getCupedSelection, resolveCupedLookbackDays } from './cuped'

export function CupedModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperimentSettings, setExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { experimentsConfig } = useValues(experimentsConfigLogic)
    const { closeCupedModal } = useActions(modalsLogic)
    const { isCupedModalOpen } = useValues(modalsLogic)

    const selection = getCupedSelection(experiment.stats_config?.cuped)
    const teamDefaultEnabled = experimentsConfig?.default_cuped_enabled ?? false
    const teamDefaultLookbackDays = experimentsConfig?.default_cuped_lookback_days ?? null
    const lookbackDays = resolveCupedLookbackDays(
        experiment.stats_config?.cuped,
        teamDefaultLookbackDays,
        DEFAULT_LOOKBACK_DAYS
    )

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        closeCupedModal()
    }

    const updateSelection = (next: CupedSelection): void => {
        if (next === 'default') {
            // Drop the cuped key entirely so the team default applies at evaluation time.
            const { cuped: _cuped, ...restStatsConfig } = experiment.stats_config ?? {}
            setExperiment({ stats_config: restStatsConfig })
            return
        }
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                cuped: {
                    ...experiment.stats_config?.cuped,
                    enabled: next === 'enabled',
                },
            },
        })
    }

    const updateLookbackDays = (lookback_days: number): void => {
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                cuped: {
                    ...experiment.stats_config?.cuped,
                    lookback_days,
                },
            },
        })
    }

    const onSave = (): void => {
        updateExperimentSettings({ stats_config: experiment.stats_config })
        closeCupedModal()
    }

    return (
        <LemonModal
            maxWidth={600}
            isOpen={isCupedModalOpen}
            onClose={onClose}
            title="CUPED variance reduction"
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
                    Use pre-experiment data to detect significant effects faster. Currently supported for mean and
                    funnel metrics.
                </p>
                <div className="flex flex-col gap-1">
                    <LemonLabel>CUPED</LemonLabel>
                    <LemonSelect<CupedSelection>
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
                        <LemonLabel>Lookback window (days)</LemonLabel>
                        <LemonInput
                            type="number"
                            min={MIN_LOOKBACK_DAYS}
                            max={MAX_LOOKBACK_DAYS}
                            value={lookbackDays}
                            onChange={(value) => {
                                if (typeof value !== 'number' || !Number.isFinite(value)) {
                                    return
                                }
                                const rounded = Math.round(value)
                                if (rounded < MIN_LOOKBACK_DAYS || rounded > MAX_LOOKBACK_DAYS) {
                                    return
                                }
                                updateLookbackDays(rounded)
                            }}
                            className="w-32"
                        />
                        <p className="text-xs text-secondary m-0">
                            Number of days before the experiment start to use as the pre-experiment window. Must be
                            between {MIN_LOOKBACK_DAYS} and {MAX_LOOKBACK_DAYS} days.
                        </p>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
