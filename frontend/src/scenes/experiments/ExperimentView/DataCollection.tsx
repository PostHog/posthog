import '../Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonModal, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'

import { Experiment, InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { formatUnitByQuantity } from '../utils'
import { EllipsisAnimation } from './components'
import { DataCollectionCalculator } from './DataCollectionCalculator'

export function DataCollection(): JSX.Element {
    const { experimentId, experiment, experimentInsightType, funnelResultsPersonsTotal, actualRunningTime } =
        useValues(experimentLogic)

    const { openExperimentCollectionGoalModal } = useActions(experimentLogic)

    const recommendedRunningTime = experiment?.parameters?.recommended_running_time || 1
    const recommendedSampleSize = experiment?.parameters?.recommended_sample_size || 100

    const experimentProgressPercent =
        experimentInsightType === InsightType.FUNNELS
            ? (funnelResultsPersonsTotal / recommendedSampleSize) * 100
            : (actualRunningTime / recommendedRunningTime) * 100

    const hasHighRunningTime = recommendedRunningTime > 62
    const GoalTooltip = (): JSX.Element => {
        if (!experiment?.parameters?.minimum_detectable_effect) {
            return <></>
        }

        return (
            <Tooltip
                title={
                    <div>
                        <div>{`Based on the Minimum Acceptable Improvement of ${experiment.parameters.minimum_detectable_effect}%.`}</div>
                        {hasHighRunningTime && (
                            <div className="mt-2">
                                Given the current data, this experiment might take a while to reach statistical
                                significance. Please make sure events are being tracked correctly and consider if this
                                timeline works for you.
                            </div>
                        )}
                    </div>
                }
            >
                <IconInfo className="text-muted-alt text-base" />
            </Tooltip>
        )
    }

    return (
        <div>
            <div className="inline-flex items-center space-x-2">
                <h2 className="font-semibold text-lg mb-0">Data collection</h2>
                <Tooltip
                    title="Estimated target for the number of participants. Actual data may reveal significance earlier or later
                    than predicted."
                >
                    <IconInfo className="text-muted-alt text-base" />
                </Tooltip>
            </div>
            <div className="mt-2 mb-1 font-semibold">{`${
                experimentProgressPercent > 100 ? 100 : experimentProgressPercent.toFixed(2)
            }% complete`}</div>
            <LemonProgress
                className="w-full border"
                bgColor="var(--bg-table)"
                size="large"
                percent={experimentProgressPercent}
            />
            {experimentInsightType === InsightType.TRENDS && (
                <div className="flex justify-between mt-0">
                    {experiment.end_date ? (
                        <div>
                            Ran for <b>{actualRunningTime}</b> {formatUnitByQuantity(actualRunningTime, 'day')}
                        </div>
                    ) : (
                        <div>
                            <b>{actualRunningTime}</b> {formatUnitByQuantity(actualRunningTime, 'day')} running
                        </div>
                    )}
                    <div className="inline-flex space-x-1 items-center">
                        {hasHighRunningTime ? (
                            <>
                                Goal:&nbsp;
                                <b> &gt; 2</b>&nbsp;months
                            </>
                        ) : (
                            <>
                                Goal:&nbsp;
                                <b>{recommendedRunningTime}</b>&nbsp;
                                {formatUnitByQuantity(recommendedRunningTime, 'day')}
                            </>
                        )}
                        <GoalTooltip />
                    </div>
                </div>
            )}
            {experimentInsightType === InsightType.FUNNELS && (
                <div className="flex justify-between mt-0">
                    {experiment.end_date ? (
                        <div>
                            Saw <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b>{' '}
                            {formatUnitByQuantity(funnelResultsPersonsTotal, 'participant')}
                        </div>
                    ) : (
                        <div>
                            <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b>{' '}
                            {formatUnitByQuantity(funnelResultsPersonsTotal, 'participant')} seen
                        </div>
                    )}
                    <div className="space-x-1 flex items-center">
                        <span>
                            Goal: <b>{humanFriendlyNumber(recommendedSampleSize)}</b>{' '}
                            {formatUnitByQuantity(recommendedSampleSize, 'participant')}
                        </span>
                        <GoalTooltip />
                    </div>
                </div>
            )}
            {!experiment.end_date && (
                <div className="w-24">
                    <LemonButton
                        className="mt-3"
                        size="small"
                        type="secondary"
                        onClick={openExperimentCollectionGoalModal}
                    >
                        Recalculate
                    </LemonButton>
                </div>
            )}
            <DataCollectionGoalModal experimentId={experimentId} />
        </div>
    )
}

export function DataCollectionGoalModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { isExperimentCollectionGoalModalOpen, goalInsightDataLoading } = useValues(experimentLogic({ experimentId }))
    const { closeExperimentCollectionGoalModal, updateExperimentCollectionGoal } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isExperimentCollectionGoalModalOpen}
            onClose={closeExperimentCollectionGoalModal}
            width={550}
            title="Recalculate estimated sample size"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        type="secondary"
                        onClick={closeExperimentCollectionGoalModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => updateExperimentCollectionGoal()}
                        type="primary"
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            {goalInsightDataLoading ? (
                <div className="flex flex-col flex-1 justify-center items-center mb-6">
                    <Animation type={AnimationType.LaptopHog} />
                    <div className="text-xs text-muted w-60">
                        <span className="mr-1">Fetching past events for the estimation</span>
                        <EllipsisAnimation />
                    </div>
                </div>
            ) : (
                <DataCollectionCalculator experimentId={experimentId} />
            )}
        </LemonModal>
    )
}
