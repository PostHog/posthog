import { IconCalculator, IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
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
            <div className="flex items-center deprecated-space-x-2 mb-2">
                <h2 className="mb-0 font-semibold text-lg leading-6">Running time</h2>
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
            <div className="relative border rounded bg-surface-primary p-4 h-[280px] overflow-y-auto">
                {!recommendedSampleSize || !recommendedRunningTime ? (
                    <div className="flex justify-center items-center h-full">
                        <div className="text-center">
                            <IconCalculator className="text-3xl mb-2 text-tertiary" />
                            <div className="text-md font-semibold leading-tight mb-3">No running time yet</div>
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
                        <div className="text-center mt-2 mb-4 text-xs text-muted">
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
