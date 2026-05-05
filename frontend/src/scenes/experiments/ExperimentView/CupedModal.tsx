import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { DEFAULT_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

export function CupedModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment, setExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeCupedModal } = useActions(modalsLogic)
    const { isCupedModalOpen } = useValues(modalsLogic)

    const enabled = experiment.stats_config?.cuped?.enabled ?? false
    const lookbackDays = experiment.stats_config?.cuped?.lookback_days ?? DEFAULT_LOOKBACK_DAYS

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        closeCupedModal()
    }

    const updateCupedConfig = (next: { enabled?: boolean; lookback_days?: number }): void => {
        setExperiment({
            stats_config: {
                ...experiment.stats_config,
                cuped: {
                    ...experiment.stats_config?.cuped,
                    ...next,
                },
            },
        })
    }

    const onSave = (): void => {
        updateExperiment({ stats_config: experiment.stats_config })
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
                    CUPED (Controlled-experiment Using Pre-Experiment Data) uses pre-experiment data to detect
                    significant effects faster. Currently supported for mean and funnel metrics.
                </p>
                <LemonSwitch
                    label="Enable CUPED"
                    checked={enabled}
                    onChange={(checked) => updateCupedConfig({ enabled: checked })}
                    bordered
                    fullWidth
                />
                {enabled && (
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
                                updateCupedConfig({ lookback_days: rounded })
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
