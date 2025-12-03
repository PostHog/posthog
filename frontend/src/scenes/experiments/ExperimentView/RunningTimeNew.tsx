import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck, IconClock, IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle/LemonProgressCircle'
import { Label } from 'lib/ui/Label/Label'

import { Experiment } from '~/types'

import { RunningTimeConfigModal } from '../RunningTimeCalculatorNew/RunningTimeConfigModal'
import {
    calculateCurrentExposures,
    calculateDaysElapsed,
    calculateExperimentTimeEstimate,
} from '../RunningTimeCalculatorNew/calculations'
import { DEFAULT_MDE, experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

export const RunningTimeNew = ({
    experiment,
    tabId,
    onClick,
}: {
    experiment: Experiment
    tabId: string
    onClick: () => void
}): JSX.Element => {
    const { orderedPrimaryMetricsWithResults, primaryMetricsResultsLoading } = useValues(
        experimentLogic({ experimentId: experiment.id, tabId })
    )
    const { updateExperiment } = useActions(experimentLogic({ experimentId: experiment.id, tabId }))
    const { closeRunningTimeConfigModal } = useActions(modalsLogic)

    const [tempMDE, setTempMDE] = useState(experiment.parameters?.minimum_detectable_effect ?? DEFAULT_MDE)

    useEffect(() => {
        setTempMDE(experiment.parameters?.minimum_detectable_effect ?? DEFAULT_MDE)
    }, [experiment.parameters?.minimum_detectable_effect])

    const firstMetric = orderedPrimaryMetricsWithResults?.[0]

    let exposures = null
    let recommendedSampleSize = null
    let exposureRate = null
    let estimatedRemainingDays = null

    if (firstMetric?.metric && firstMetric?.result?.baseline && experiment.start_date) {
        const daysElapsed = calculateDaysElapsed(experiment.start_date)
        const currentExposures = calculateCurrentExposures(firstMetric.result)

        if (daysElapsed && daysElapsed >= 1 && currentExposures && currentExposures >= 100) {
            const estimates = calculateExperimentTimeEstimate(
                firstMetric.metric,
                firstMetric.result,
                experiment,
                tempMDE
            )
            exposures = estimates.currentExposures
            recommendedSampleSize = estimates.recommendedSampleSize
            exposureRate = estimates.exposureRate
            estimatedRemainingDays = estimates.estimatedRemainingDays
        }
    }

    const handleMDEChange = (value: number): void => {
        setTempMDE(value)
    }

    const handleSave = (): void => {
        updateExperiment({
            parameters: {
                ...experiment.parameters,
                minimum_detectable_effect: tempMDE,
            },
        })
        closeRunningTimeConfigModal()
    }

    const handleCancel = (): void => {
        setTempMDE(experiment.parameters?.minimum_detectable_effect ?? DEFAULT_MDE)
        closeRunningTimeConfigModal()
    }

    return (
        <>
            <div className="flex flex-col">
                <Label intent="menu">Remaining time</Label>
                <div className="inline-flex deprecated-space-x-2 items-center">
                    {primaryMetricsResultsLoading ? (
                        <span>Loading...</span>
                    ) : estimatedRemainingDays === null ? (
                        <span className="inline-flex items-center gap-1">
                            <IconClock />
                            Pending
                        </span>
                    ) : estimatedRemainingDays === 0 ? (
                        <span className="inline-flex items-center gap-1">
                            <IconCheck className="text-success" />
                            Complete
                        </span>
                    ) : (
                        <>
                            <span>
                                ~{Math.ceil(estimatedRemainingDays)} day
                                {Math.ceil(estimatedRemainingDays) !== 1 ? 's' : ''}
                            </span>
                            <LemonProgressCircle
                                progress={
                                    exposures && recommendedSampleSize
                                        ? Math.min(exposures / recommendedSampleSize, 1)
                                        : 0
                                }
                                size={22}
                            />
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
            <RunningTimeConfigModal
                estimatedRemainingDays={estimatedRemainingDays}
                exposures={exposures}
                recommendedSampleSize={recommendedSampleSize}
                exposureRate={exposureRate}
                mde={tempMDE}
                onMDEChange={handleMDEChange}
                onSave={handleSave}
                onCancel={handleCancel}
            />
        </>
    )
}
