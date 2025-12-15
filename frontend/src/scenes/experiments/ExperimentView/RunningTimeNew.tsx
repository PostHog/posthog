import { useValues } from 'kea'

import { IconCheck, IconClock, IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle/LemonProgressCircle'
import { Label } from 'lib/ui/Label/Label'

import { Experiment } from '~/types'

import { RunningTimeConfigModal } from '../RunningTimeCalculatorNew/RunningTimeConfigModal'
import { runningTimeLogic } from '../RunningTimeCalculatorNew/runningTimeLogic'

export const RunningTimeNew = ({
    experiment,
    tabId,
    onClick,
}: {
    experiment: Experiment
    tabId: string
    onClick: () => void
}): JSX.Element => {
    const {
        remainingDays,
        currentExposures,
        targetSampleSize,
        isComplete,
        isManualMode,
        primaryMetricsResultsLoading,
    } = useValues(runningTimeLogic({ experimentId: experiment.id, tabId }))

    const showProgress = currentExposures !== null && targetSampleSize !== null

    return (
        <>
            <div className="flex flex-col">
                <Label intent="menu">Remaining time</Label>
                <div className="inline-flex items-center gap-2">
                    {primaryMetricsResultsLoading && !isManualMode ? (
                        <span>Loading...</span>
                    ) : remainingDays === null ? (
                        <span className="inline-flex items-center gap-1">
                            <IconClock />
                            Pending
                        </span>
                    ) : isComplete ? (
                        <span className="inline-flex items-center gap-1">
                            <IconCheck className="text-success" />
                            Complete
                        </span>
                    ) : (
                        <>
                            <span>
                                ~{Math.ceil(remainingDays)} day
                                {Math.ceil(remainingDays) !== 1 ? 's' : ''}
                            </span>
                            {showProgress && (
                                <LemonProgressCircle
                                    progress={Math.min(currentExposures / targetSampleSize, 1)}
                                    size={22}
                                />
                            )}
                        </>
                    )}
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={onClick}
                        icon={<IconGear />}
                        tooltip="Configure"
                    />
                </div>
            </div>
            <RunningTimeConfigModal experimentId={experiment.id} tabId={tabId} />
        </>
    )
}
