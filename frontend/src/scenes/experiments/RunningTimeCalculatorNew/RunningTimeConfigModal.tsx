import { useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Label } from 'lib/ui/Label/Label'

import { modalsLogic } from '../modalsLogic'

export interface RunningTimeConfigModalProps {
    estimatedRemainingDays: number | null
    exposures: number | null
    recommendedSampleSize: number | null
    exposureRate: number | null
    mde: number
    onMDEChange: (value: number) => void
    onSave: () => void
    onCancel: () => void
}

export function RunningTimeConfigModal({
    estimatedRemainingDays,
    exposures,
    recommendedSampleSize,
    exposureRate,
    mde,
    onMDEChange,
    onSave,
    onCancel,
}: RunningTimeConfigModalProps): JSX.Element {
    const { isRunningTimeConfigModalOpen } = useValues(modalsLogic)

    return (
        <LemonModal
            isOpen={isRunningTimeConfigModalOpen}
            onClose={onCancel}
            title="Running time configuration"
            footer={
                <div className="flex items-center gap-2 justify-end">
                    <LemonButton type="secondary" onClick={onCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={onSave}>
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                {estimatedRemainingDays === null ? (
                    <LemonBanner type="info">
                        Waiting for sufficient data to calculate time estimates. Need at least 1 day and 100 exposures.
                    </LemonBanner>
                ) : (
                    <>
                        <div>
                            <Label intent="menu">Remaining time</Label>
                            <div className="metric-cell">
                                {estimatedRemainingDays === 0 ? (
                                    <span className="inline-flex items-center gap-1">
                                        <IconCheck className="text-success" />
                                        Complete
                                    </span>
                                ) : (
                                    `~${Math.ceil(estimatedRemainingDays)} day${Math.ceil(estimatedRemainingDays) !== 1 ? 's' : ''}`
                                )}
                            </div>
                        </div>
                        <div>
                            <Label intent="menu">Progress</Label>
                            <div className="metric-cell">
                                {exposures && recommendedSampleSize
                                    ? `${exposures.toLocaleString()} / ${recommendedSampleSize.toLocaleString()} exposures`
                                    : '—'}
                            </div>
                        </div>
                        <div>
                            <Label intent="menu">Rate</Label>
                            <div className="metric-cell">
                                {exposureRate ? `~${Math.round(exposureRate).toLocaleString()} exposures/day` : '—'}
                            </div>
                        </div>
                    </>
                )}
                <div>
                    <Label intent="menu">Minimum detectable effect</Label>
                    <div className="flex items-center gap-3">
                        <div className="flex-[3]">
                            <LemonSlider
                                value={mde}
                                onChange={(value) => onMDEChange(Math.round(value * 10) / 10)}
                                min={1}
                                max={100}
                                step={0.1}
                            />
                        </div>
                        <div className="flex-1 flex items-center gap-1">
                            <LemonInput
                                type="number"
                                value={mde}
                                onChange={(value) => onMDEChange(Number(value))}
                                min={1}
                                max={100}
                                step={0.1}
                                className="flex-1"
                            />
                            <span className="text-muted">%</span>
                        </div>
                    </div>
                    <div className="text-xs text-muted mt-1">
                        The smallest change you want to detect. Lower values require more data and longer run times.
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
