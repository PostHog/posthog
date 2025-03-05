import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'

import { experimentLogic } from '../experimentLogic'
import { getMetricTitle } from '../MetricsView/DeltaChart'
import { runningTimeCalculatorLogic, TIMEFRAME_HISTORICAL_DATA_DAYS } from './runningTimeCalculatorLogic'

export function RunningTimeCalculatorModal(): JSX.Element {
    const { experimentId, isCalculateRunningTimeModalOpen } = useValues(experimentLogic)
    const { closeCalculateRunningTimeModal, updateExperiment } = useActions(experimentLogic)

    const {
        experiment,
        minimumDetectableEffect,
        recommendedSampleSize,
        recommendedRunningTime,
        standardDeviation,
        metricIndex,
        uniqueUsers,
        averageEventsPerUser,
        averagePropertyValuePerUser,
        metricResultLoading,
    } = useValues(runningTimeCalculatorLogic({ experimentId }))
    const { setMinimumDetectableEffect, setMetricIndex } = useActions(runningTimeCalculatorLogic({ experimentId }))

    return (
        <LemonModal
            isOpen={isCalculateRunningTimeModalOpen}
            onClose={closeCalculateRunningTimeModal}
            width={700}
            title="Calculate estimated running time"
            footer={
                <div className="flex items-center w-full">
                    <div className="flex items-center gap-2 ml-auto">
                        <LemonButton
                            form="edit-experiment-metric-form"
                            type="secondary"
                            onClick={closeCalculateRunningTimeModal}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="edit-experiment-metric-form"
                            onClick={() => {
                                updateExperiment({
                                    parameters: {
                                        ...experiment?.parameters,
                                        recommended_running_time: recommendedRunningTime,
                                        recommended_sample_size: recommendedSampleSize || undefined,
                                    },
                                })
                                closeCalculateRunningTimeModal()
                            }}
                            type="primary"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="space-y-6">
                {/* Step 1: Metric selection */}
                <div className="rounded bg-light p-4 space-y-3">
                    <div className="flex items-center gap-2">
                        <span className="rounded-full bg-muted text-white w-6 h-6 flex items-center justify-center font-semibold">
                            1
                        </span>
                        <h4 className="font-semibold m-0">Select metric</h4>
                    </div>
                    <p className="text-muted mb-3">
                        Choose a metric to analyze. We'll use historical data from this metric to estimate the
                        experiment duration.
                    </p>
                    <div className="space-y-2">
                        <div className="mb-4">
                            <div className="card-secondary mb-2">Experiment metric</div>
                            <LemonSelect
                                options={experiment.metrics.map((metric, index) => ({
                                    label: (
                                        <div className="cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis flex-grow flex items-center">
                                            <span className="mr-1">{index + 1}.</span>
                                            {getMetricTitle(metric)}
                                        </div>
                                    ),
                                    value: index,
                                }))}
                                value={metricIndex}
                                onChange={(value) => {
                                    if (value !== null) {
                                        setMetricIndex(value)
                                    }
                                }}
                            />
                        </div>

                        {metricResultLoading ? (
                            <div className="border-t pt-2">
                                <div className="h-[100px] flex items-center justify-center">
                                    <Spinner className="text-3xl transform -translate-y-[-10px]" />
                                </div>
                            </div>
                        ) : uniqueUsers !== null && standardDeviation !== null ? (
                            <div className="border-t pt-2">
                                <div className="grid grid-cols-3 gap-4">
                                    <div>
                                        <div className="card-secondary">Unique users</div>
                                        <div className="font-semibold">
                                            ~{humanFriendlyNumber(uniqueUsers || 0, 0)} persons
                                        </div>
                                        <div className="text-xs text-muted">
                                            Last {TIMEFRAME_HISTORICAL_DATA_DAYS} days
                                        </div>
                                    </div>
                                    {averageEventsPerUser !== null && (
                                        <div>
                                            <div className="card-secondary">Avg. events per user</div>
                                            <div className="font-semibold">
                                                ~{humanFriendlyNumber(averageEventsPerUser || 0, 0)}
                                            </div>
                                        </div>
                                    )}
                                    {averagePropertyValuePerUser !== null && (
                                        <div>
                                            <div className="card-secondary">Avg. property value per user</div>
                                            <div className="font-semibold">
                                                ~{humanFriendlyNumber(averagePropertyValuePerUser, 0)}
                                            </div>
                                        </div>
                                    )}
                                    <div>
                                        <div className="card-secondary">Estimated standard deviation</div>
                                        <div className="font-semibold">
                                            ~{humanFriendlyNumber(standardDeviation, 0)}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ) : null}
                    </div>
                </div>

                {!metricResultLoading && uniqueUsers !== null && (
                    <>
                        {/* Step 2: MDE configuration */}
                        <div className="rounded bg-light p-4 space-y-3">
                            <div className="flex items-center gap-2">
                                <span className="rounded-full bg-muted text-white w-6 h-6 flex items-center justify-center font-semibold">
                                    2
                                </span>
                                <h4 className="font-semibold m-0">Choose minimum detectable effect</h4>
                            </div>
                            <p className="text-muted">
                                The minimum detectable effect (MDE) is the smallest improvement you want to be able to
                                detect with statistical significance. A smaller MDE requires more participants but can
                                detect subtler changes.
                            </p>
                            <div className="flex items-center gap-2">
                                <LemonInput
                                    className="w-[80px]"
                                    min={0}
                                    step={0.1}
                                    type="number"
                                    value={minimumDetectableEffect}
                                    onChange={(newValue) => {
                                        if (newValue) {
                                            setMinimumDetectableEffect(newValue)
                                        }
                                    }}
                                />
                                <div>%</div>
                            </div>
                        </div>

                        {/* Step 3: Results */}
                        {recommendedSampleSize !== null && recommendedRunningTime !== null && (
                            <div className="rounded bg-light p-4 space-y-3">
                                <div className="flex items-center gap-2">
                                    <span className="rounded-full bg-muted text-white w-6 h-6 flex items-center justify-center font-semibold">
                                        3
                                    </span>
                                    <h4 className="font-semibold m-0">Estimated experiment size & duration</h4>
                                </div>
                                <p className="text-muted">
                                    These are just statistical estimates – you can conclude the experiment earlier if a
                                    significant effect is detected. Running shorter may make results less reliable.
                                </p>
                                <div className="grid grid-cols-2 gap-4 pt-2">
                                    <div>
                                        <div className="card-secondary">Recommended sample size</div>
                                        <div className="text-lg font-semibold">
                                            ~{humanFriendlyNumber(recommendedSampleSize, 0)} users
                                        </div>
                                    </div>
                                    <div>
                                        <div className="card-secondary">Estimated running time</div>
                                        <div className="text-lg font-semibold">
                                            ~{humanFriendlyNumber(recommendedRunningTime, 1)} days
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        </LemonModal>
    )
}
