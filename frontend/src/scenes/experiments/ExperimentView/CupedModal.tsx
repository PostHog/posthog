import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

export const DEFAULT_LOOKBACK_DAYS = 14
export const MIN_LOOKBACK_DAYS = 1
export const MAX_LOOKBACK_DAYS = 365

const clampLookbackDays = (value: number): number =>
    Math.min(Math.max(Math.round(value), MIN_LOOKBACK_DAYS), MAX_LOOKBACK_DAYS)

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
        const cupedConfig = experiment.stats_config?.cuped
        const clampedLookback = clampLookbackDays(cupedConfig?.lookback_days ?? DEFAULT_LOOKBACK_DAYS)
        updateExperiment({
            stats_config: {
                ...experiment.stats_config,
                cuped: {
                    ...cupedConfig,
                    lookback_days: clampedLookback,
                },
            },
        })
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
                    CUPED (Controlled-experiment Using Pre-Experiment Data) reduces variance by adjusting metrics with
                    pre-experiment data, which can shorten the time required to detect a significant effect. Currently
                    supported for mean metrics.
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
                                if (typeof value !== 'number' || !Number.isFinite(value) || value < MIN_LOOKBACK_DAYS) {
                                    return
                                }
                                updateCupedConfig({ lookback_days: value })
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
