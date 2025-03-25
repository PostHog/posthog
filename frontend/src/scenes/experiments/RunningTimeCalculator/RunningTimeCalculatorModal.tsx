import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'

import { ExperimentMetric, ExperimentMetricType } from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'
import { MetricTitle } from '../MetricsView/MetricTitle'
import {
    AverageEventsPerUserPanel,
    AveragePropertyValuePerUserPanel,
    StandardDeviationPanel,
    UniqueUsersPanel,
} from './components'
import { ConversionRateInputType, runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'

const MeanMetricDataPanel = (): JSX.Element => {
    const { experimentId } = useValues(experimentLogic)
    const { uniqueUsers, averageEventsPerUser, averagePropertyValuePerUser, standardDeviation } = useValues(
        runningTimeCalculatorLogic({ experimentId })
    )
    return (
        <div className="grid grid-cols-3 gap-4">
            <UniqueUsersPanel uniqueUsers={uniqueUsers} />
            <AverageEventsPerUserPanel averageEventsPerUser={averageEventsPerUser} />
            <AveragePropertyValuePerUserPanel averagePropertyValuePerUser={averagePropertyValuePerUser} />
            <StandardDeviationPanel standardDeviation={standardDeviation} />
        </div>
    )
}

const FunnelMetricDataPanel = (): JSX.Element => {
    const { experimentId } = useValues(experimentLogic)
    const { conversionRateInputType, uniqueUsers, automaticConversionRateDecimal, manualConversionRate } = useValues(
        runningTimeCalculatorLogic({ experimentId })
    )
    const { setConversionRateInputType, setManualConversionRate } = useActions(
        runningTimeCalculatorLogic({ experimentId })
    )
    return (
        <div>
            <div className="grid grid-cols-3 gap-4">
                <UniqueUsersPanel uniqueUsers={uniqueUsers} />
                <div>
                    <div className="card-secondary">
                        <span>Conversion rate input</span>
                        <Tooltip
                            className="ml-1"
                            title={
                                <>
                                    <strong>Automatic:</strong> Uses historical conversion rate between your exposure
                                    event and the conversion event. It may not always be representative of expected
                                    performance.
                                    <br />
                                    <br />
                                    <strong>Manual:</strong> Allows you to set a custom conversion rate based on your
                                    own knowledge of the funnel.
                                </>
                            }
                        >
                            <IconInfo className="text-secondary ml-1" />
                        </Tooltip>
                    </div>
                    <LemonSegmentedButton
                        className="mt-2"
                        size="small"
                        options={[
                            {
                                label: 'Manual',
                                value: ConversionRateInputType.MANUAL,
                            },
                            {
                                label: 'Automatic',
                                value: ConversionRateInputType.AUTOMATIC,
                            },
                        ]}
                        onChange={(value) => {
                            setConversionRateInputType(value)
                        }}
                        value={conversionRateInputType}
                    />
                    {conversionRateInputType === ConversionRateInputType.MANUAL && (
                        <div className="flex items-center gap-2">
                            <LemonInput
                                className="w-[80px] mt-2"
                                min={0}
                                step={0.01}
                                max={100}
                                type="number"
                                value={manualConversionRate || undefined}
                                onChange={(newValue) => {
                                    if (newValue !== null && newValue !== undefined && newValue >= 0) {
                                        setManualConversionRate(newValue)
                                    }
                                }}
                            />
                            <div>%</div>
                        </div>
                    )}
                    {conversionRateInputType === ConversionRateInputType.AUTOMATIC && (
                        <div className="font-semibold mt-2">
                            ~{humanFriendlyNumber(automaticConversionRateDecimal * 100, 2)}%
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

export function RunningTimeCalculatorModal(): JSX.Element {
    const { experimentId, isCalculateRunningTimeModalOpen } = useValues(experimentLogic)
    const { closeCalculateRunningTimeModal, updateExperiment } = useActions(experimentLogic)

    const {
        experiment,
        metric,
        minimumDetectableEffect,
        recommendedSampleSize,
        recommendedRunningTime,
        metricIndex,
        uniqueUsers,
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
                                        minimum_detectable_effect: minimumDetectableEffect || undefined,
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
            <div className="deprecated-space-y-6">
                {/* Step 1: Metric selection */}
                <div className="rounded bg-light p-4 deprecated-space-y-3">
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
                    <div className="deprecated-space-y-2">
                        <div className="mb-4">
                            <div className="card-secondary mb-2">Experiment metric</div>
                            <LemonSelect
                                options={experiment.metrics.map((metric, index) => ({
                                    label: (
                                        <div className="cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis flex-grow flex items-center">
                                            <span className="mr-1">{index + 1}.</span>
                                            <MetricTitle metric={metric} />
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
                        ) : (
                            <div className="border-t pt-2">
                                {(metric as ExperimentMetric)?.metric_type === ExperimentMetricType.MEAN && (
                                    <MeanMetricDataPanel />
                                )}
                                {(metric as ExperimentMetric)?.metric_type === ExperimentMetricType.FUNNEL && (
                                    <FunnelMetricDataPanel />
                                )}
                            </div>
                        )}
                    </div>
                </div>

                {!metricResultLoading && uniqueUsers !== null && (
                    <>
                        {/* Step 2: MDE configuration */}
                        <div className="rounded bg-light p-4 deprecated-space-y-3">
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
                            <div className="rounded bg-light p-4 deprecated-space-y-3">
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
