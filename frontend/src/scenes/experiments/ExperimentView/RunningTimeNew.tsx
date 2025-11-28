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
    const { displayValues, isComplete, primaryMetricsResultsLoading, isManualMode } = useValues(
        runningTimeLogic({ experimentId: experiment.id, tabId })
    )

    return (
        <>
            <div className="flex flex-col">
                <Label intent="menu">Remaining time</Label>
                <div className="inline-flex items-center gap-2">
                    {primaryMetricsResultsLoading && !isManualMode ? (
                        <span>Loading...</span>
                    ) : displayValues.estimatedDays === null ? (
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
                                ~{Math.ceil(displayValues.estimatedDays)} day
                                {Math.ceil(displayValues.estimatedDays) !== 1 ? 's' : ''}
                            </span>
                            {displayValues.exposures && displayValues.sampleSize && (
                                <LemonProgressCircle
                                    progress={Math.min(displayValues.exposures / displayValues.sampleSize, 1)}
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
