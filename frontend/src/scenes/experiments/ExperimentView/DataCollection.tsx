import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { humanFriendlyNumber } from 'lib/utils'

import { Experiment, InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { formatUnitByQuantity } from '../utils'
import { EllipsisAnimation } from './components'
import { DataCollectionCalculator } from './DataCollectionCalculator'
import { modalsLogic } from '../modalsLogic'

export function DataCollection(): JSX.Element {
    const {
        experimentId,
        experiment,
        getInsightType,
        funnelResultsPersonsTotal,
        actualRunningTime,
        minimumDetectableEffect,
        firstPrimaryMetric,
    } = useValues(experimentLogic)

    const { openExperimentCollectionGoalModal } = useActions(modalsLogic)

    const insightType = getInsightType(firstPrimaryMetric)

    const recommendedRunningTime = experiment?.parameters?.recommended_running_time || 1
    const recommendedSampleSize = experiment?.parameters?.recommended_sample_size || 100

    const experimentProgressPercent =
        insightType === InsightType.FUNNELS
            ? (funnelResultsPersonsTotal(0) / recommendedSampleSize) * 100
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
                        <div>{`Based on the Minimum detectable effect of ${experiment.parameters.minimum_detectable_effect}%.`}</div>
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
                <IconInfo className="text-secondary text-base" />
            </Tooltip>
        )
    }

    return (
        <div>
            <div className="inline-flex items-center deprecated-space-x-2">
                <h2 className="font-semibold text-lg mb-0">Data collection</h2>
                <Tooltip
                    title="Estimated target for the number of participants. Actual data may reveal significance earlier or later
                    than predicted."
                >
                    <IconInfo className="text-secondary text-base" />
                </Tooltip>
            </div>
            <div className="flex">
                <div className="w-3/5 pr-4">
                    <div className="mt-2 mb-1 font-semibold">{`${
                        experimentProgressPercent > 100 ? 100 : experimentProgressPercent.toFixed(2)
                    }% complete`}</div>
                    <LemonProgress
                        className="w-full border"
                        bgColor="var(--bg-table)"
                        size="medium"
                        percent={experimentProgressPercent}
                    />
                    {insightType === InsightType.TRENDS && (
                        <div className="flex justify-between mt-0">
                            <span className="flex items-center text-xs">
                                Completed&nbsp;
                                <b>{actualRunningTime} of</b>
                                {hasHighRunningTime ? (
                                    <b>&nbsp; &gt; 60 days</b>
                                ) : (
                                    <span>
                                        &nbsp;
                                        <b>{recommendedRunningTime}</b>{' '}
                                        {formatUnitByQuantity(recommendedRunningTime, 'day')}
                                    </span>
                                )}
                                <span className="ml-1 text-xs">
                                    <GoalTooltip />
                                </span>
                            </span>
                        </div>
                    )}
                    {insightType === InsightType.FUNNELS && (
                        <div className="flex justify-between mt-0">
                            <div className="deprecated-space-x-1 flex items-center text-xs">
                                <span>
                                    Saw&nbsp;
                                    <b>
                                        {humanFriendlyNumber(funnelResultsPersonsTotal(0))} of{' '}
                                        {humanFriendlyNumber(recommendedSampleSize)}{' '}
                                    </b>{' '}
                                    {formatUnitByQuantity(recommendedSampleSize, 'participant')}
                                </span>
                                <GoalTooltip />
                            </div>
                        </div>
                    )}
                </div>
                <LemonDivider className="my-0" vertical />
                <div className="w-2/5 pl-4">
                    <div className={`text-lg font-semibold ${experiment.end_date ? 'mt-4' : ''}`}>
                        {minimumDetectableEffect}%
                    </div>
                    <div className="text-xs deprecated-space-x-1 text-sm flex">
                        <span>Minimum detectable effect</span>
                        <Tooltip
                            title={
                                <div className="deprecated-space-y-2">
                                    <div>
                                        The Minimum detectable effect represents the smallest change that you want to be
                                        able to detect in your experiment.
                                    </div>
                                    <div>
                                        To make things easier, we initially set this value to a reasonable default.
                                        However, we encourage you to review and adjust it based on your specific goals.
                                    </div>
                                    <div>
                                        Read more in the{' '}
                                        <Link to="https://posthog.com/docs/experiments/sample-size-running-time#minimum-detectable-effect-mde">
                                            documentation.
                                        </Link>
                                    </div>
                                </div>
                            }
                            closeDelayMs={200}
                        >
                            <IconInfo className="text-secondary text-base" />
                        </Tooltip>
                    </div>
                    {!experiment.end_date && (
                        <div className="w-24">
                            <LemonButton
                                className="mt-2"
                                size="xsmall"
                                type="secondary"
                                onClick={openExperimentCollectionGoalModal}
                            >
                                <span className="px-0">Edit</span>
                            </LemonButton>
                        </div>
                    )}
                    <DataCollectionGoalModal experimentId={experimentId} />
                </div>
            </div>
        </div>
    )
}

export function DataCollectionGoalModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { getInsightType, firstPrimaryMetric, trendMetricInsightLoading, funnelMetricInsightLoading } = useValues(
        experimentLogic({ experimentId })
    )
    const { updateExperimentCollectionGoal, restoreUnmodifiedExperiment } = useActions(
        experimentLogic({ experimentId })
    )
    const { closeExperimentCollectionGoalModal } = useActions(modalsLogic)
    const { isExperimentCollectionGoalModalOpen } = useValues(modalsLogic)

    const isInsightLoading =
        getInsightType(firstPrimaryMetric) === InsightType.TRENDS
            ? trendMetricInsightLoading
            : funnelMetricInsightLoading

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
                        onClick={() => {
                            restoreUnmodifiedExperiment()
                            closeExperimentCollectionGoalModal()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            updateExperimentCollectionGoal()
                            closeExperimentCollectionGoalModal()
                        }}
                        type="primary"
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            {isInsightLoading ? (
                <div className="flex flex-col flex-1 justify-center items-center mb-6">
                    <LoadingBar />
                    <div className="text-xs text-secondary w-60">
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
