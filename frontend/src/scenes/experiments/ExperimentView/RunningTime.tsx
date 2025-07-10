import { useActions, useValues } from 'kea'

import { IconCalculator, IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

export function RunningTime(): JSX.Element {
    const { experiment, actualRunningTime } = useValues(experimentLogic)
    const { openCalculateRunningTimeModal } = useActions(modalsLogic)

    const recommendedSampleSize = experiment.parameters.recommended_sample_size
    const minimumDetectableEffect = experiment.parameters.minimum_detectable_effect
    const recommendedRunningTime = experiment.parameters.recommended_running_time

    return (
        <div>
            <div className="deprecated-space-x-2 mb-2 flex items-center">
                <h2 className="mb-0 text-lg font-semibold leading-6">Running time</h2>
                {recommendedRunningTime ? (
                    <LemonButton
                        icon={<IconPencil fontSize="12" />}
                        size="xsmall"
                        className="flex items-center gap-2"
                        type="secondary"
                        onClick={() => openCalculateRunningTimeModal()}
                    />
                ) : null}
            </div>
            <div className="bg-surface-primary relative h-[280px] overflow-y-auto rounded border p-4">
                {!recommendedSampleSize || !recommendedRunningTime ? (
                    <div className="flex h-full items-center justify-center">
                        <div className="text-center">
                            <IconCalculator className="text-tertiary mb-2 text-3xl" />
                            <div className="text-md mb-3 font-semibold leading-tight">No running time yet</div>
                            <div className="flex justify-center">
                                <LemonButton
                                    icon={<IconPencil fontSize="12" />}
                                    size="xsmall"
                                    className="flex items-center gap-2"
                                    type="secondary"
                                    onClick={() => openCalculateRunningTimeModal()}
                                >
                                    Calculate running time
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                ) : (
                    <>
                        <LemonProgress
                            className="w-full border"
                            bgColor="var(--bg-table)"
                            size="medium"
                            percent={(actualRunningTime / recommendedRunningTime) * 100}
                        />
                        <div className="text-muted mb-4 mt-2 text-center text-xs">
                            {actualRunningTime} of {humanFriendlyNumber(recommendedRunningTime, 0)} days completed (
                            {Math.round((actualRunningTime / recommendedRunningTime) * 100)}%)
                        </div>

                        <div className="space-y-3">
                            <div>
                                <div className="card-secondary mb-1">Recommended sample size</div>
                                <div className="text-sm font-semibold">
                                    {humanFriendlyNumber(recommendedSampleSize, 0)} users
                                </div>
                            </div>
                            <div>
                                <div className="card-secondary mb-1">Estimated running time</div>
                                <div className="text-sm font-semibold">
                                    {humanFriendlyNumber(recommendedRunningTime, 0)} days
                                </div>
                            </div>
                            <div>
                                <div className="card-secondary mb-1">Minimum detectable effect</div>
                                <div className="text-sm font-semibold">{minimumDetectableEffect}%</div>
                            </div>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
