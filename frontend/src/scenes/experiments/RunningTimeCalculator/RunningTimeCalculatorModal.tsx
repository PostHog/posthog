import { LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { humanFriendlyNumber } from 'lib/utils'
import { useState } from 'react'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { DEFAULT_MDE } from '../experimentLogic'
import { EventSelectorStep } from './EventSelectorStep'
import { calculateRecommendedSampleSize, calculateVariance } from './experimentStatisticsUtils'
import { MetricSelectorStep } from './MetricSelectorStep'
import {
    ConversionRateInputType,
    ExposureEstimateConfig,
    runningTimeCalculatorLogic,
    TIMEFRAME_HISTORICAL_DATA_DAYS,
} from './runningTimeCalculatorLogic'
import { RunningTimeCalculatorModalFooter } from './RunningTimeCalculatorModalFooter'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'

type RunningTimeCalculatorModalProps = {
    experiment: Experiment
    isOpen: boolean
    onClose: () => void
    onSave: (
        exposureEstimateConfig: ExposureEstimateConfig | null,
        minimumDetectableEffect: number,
        recommendedSampleSize: number,
        recommendedRunningTime: number
    ) => void
}

const defaultExposureEstimateConfig: ExposureEstimateConfig = {
    eventFilter: {
        event: '$pageview',
        name: '$pageview',
        properties: [],
        entityType: TaxonomicFilterGroupType.Events,
    },
    metric: null as ExperimentMetric | null,
    conversionRateInputType: ConversionRateInputType.AUTOMATIC,
    manualConversionRate: 2,
    uniqueUsers: null,
}

export function RunningTimeCalculatorModal({
    experiment,
    isOpen,
    onClose,
    onSave,
}: RunningTimeCalculatorModalProps): JSX.Element {
    // Extrct the experiment Id and the metrics from the experiment
    // If the experiment change (it shouldn't), a re-render will happen.
    const { id: experimentId, metrics } = experiment

    /**
     * Exposure Estimate Config Global State and Actions.
     * Without kea, this would be a context for local state,
     * and swr for server state.
     * We only need a Kea for fetching the exposure estimate.
     */
    const { exposureEstimate, exposureEstimateLoading } = useValues(runningTimeCalculatorLogic({ experimentId }))
    const { loadExposureEstimate } = useActions(runningTimeCalculatorLogic({ experimentId }))

    /**
     * Exposure Estimate Config Local State.
     * This is the config that the user has selected.
     * It's initializeed with the saved config.
     */
    const [exposureEstimateConfig, setExposureEstimateConfig] = useState<ExposureEstimateConfig | null>(
        experiment.parameters.exposure_estimate_config ?? defaultExposureEstimateConfig
    )

    // console.log({ experiment, exposureEstimate, exposureEstimateConfig, metrics })

    const [minimumDetectableEffect, setMinimumDetectableEffect] = useState(
        experiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE
    )

    const hasSavedValues =
        experiment.parameters.recommended_sample_size != null && experiment.parameters.recommended_running_time != null

    const variance = calculateVariance(
        exposureEstimateConfig?.metric as ExperimentMetric,
        exposureEstimate?.averageEventsPerUser ?? 0,
        exposureEstimate?.averagePropertyValuePerUser ?? 0
    )

    // Only calculate new values if we have exposure estimate and no saved values
    const calculatedSampleSize =
        !hasSavedValues && exposureEstimate && exposureEstimateConfig?.metric
            ? calculateRecommendedSampleSize(
                  exposureEstimateConfig.metric,
                  minimumDetectableEffect,
                  variance ?? 0,
                  exposureEstimate.averageEventsPerUser ?? 0,
                  exposureEstimate.averagePropertyValuePerUser ?? 0,
                  exposureEstimate.automaticConversionRateDecimal ?? 0,
                  exposureEstimate.manualConversionRate ?? 0,
                  exposureEstimateConfig.conversionRateInputType,
                  metrics.length
              )
            : null

    const calculatedRunningTime =
        !hasSavedValues && exposureEstimate?.uniqueUsers && calculatedSampleSize
            ? calculatedSampleSize / (exposureEstimate.uniqueUsers / TIMEFRAME_HISTORICAL_DATA_DAYS)
            : null

    // Use saved values if they exist, otherwise use calculated values
    const recommendedSampleSize = hasSavedValues ? experiment.parameters.recommended_sample_size : calculatedSampleSize

    const recommendedRunningTime = hasSavedValues
        ? experiment.parameters.recommended_running_time
        : calculatedRunningTime

    // console.log('>>>>>>>>> minimumDetectableEffect', minimumDetectableEffect)
    // console.log('>>>>>>>>> variance', variance)
    // console.log('>>>>>>>>> calculatedSampleSize', calculatedSampleSize)
    // console.log('>>>>>>>>> calculatedRunningTime', calculatedRunningTime)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={700}
            title="Calculate estimated running time"
            footer={
                <RunningTimeCalculatorModalFooter
                    onClose={onClose}
                    onSave={() =>
                        onSave(
                            exposureEstimateConfig,
                            minimumDetectableEffect,
                            recommendedSampleSize,
                            recommendedRunningTime
                        )
                    }
                />
            }
        >
            <EventSelectorStep
                exposureEstimateConfig={exposureEstimateConfig ?? null}
                onSetFilter={(filter) =>
                    setExposureEstimateConfig({
                        ...(exposureEstimateConfig ?? {
                            metric: null,
                            conversionRateInputType: ConversionRateInputType.AUTOMATIC,
                            manualConversionRate: null,
                            uniqueUsers: null,
                        }),

                        eventFilter: {
                            event: filter.id,
                            name: filter.name,
                            properties: filter.properties,
                            entityType:
                                filter.type === 'events'
                                    ? TaxonomicFilterGroupType.Events
                                    : TaxonomicFilterGroupType.Actions,
                        },
                    })
                }
            />
            {exposureEstimateConfig && (
                <MetricSelectorStep
                    experimentId={experimentId}
                    experimentMetrics={metrics as ExperimentMetric[]}
                    exposureEstimateConfig={exposureEstimateConfig}
                    onChangeMetric={(metric) => {
                        /**
                         * update the state with the new metric for the
                         * exposure estimate.
                         */
                        setExposureEstimateConfig({
                            ...exposureEstimateConfig,
                            metric,
                        })

                        /**
                         * Load the exposure estimate for the new metric.
                         */
                        loadExposureEstimate(experiment, exposureEstimateConfig, metric)
                    }}
                    onChangeFunnelConversionRateType={(type) => {
                        setExposureEstimateConfig({
                            ...exposureEstimateConfig,
                            conversionRateInputType: type,
                        })
                    }}
                />
            )}
            <div className="deprecated-space-y-6">
                {(experiment?.parameters?.minimum_detectable_effect ||
                    (!exposureEstimateLoading && exposureEstimate)) && (
                    <>
                        <RunningTimeCalculatorModalStep
                            stepNumber={3}
                            title="Choose minimum detectable effect"
                            description="The minimum detectable effect (MDE) is the smallest relative improvement you want to be able to detect with statistical significance. A smaller MDE requires more participants but can detect subtler changes."
                        >
                            <div className="flex items-center gap-2">
                                <LemonInput
                                    className="w-[80px]"
                                    min={0}
                                    step={1}
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
                        </RunningTimeCalculatorModalStep>
                        {/* Step 3: Results */}
                        {recommendedSampleSize !== null && recommendedRunningTime !== null && (
                            <RunningTimeCalculatorModalStep
                                stepNumber={4}
                                title="Estimated experiment size & duration"
                                description="These are just statistical estimates – you can conclude the experiment earlier if a significant effect is detected. Running shorter may make results less reliable."
                            >
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
                            </RunningTimeCalculatorModalStep>
                        )}
                    </>
                )}
            </div>
        </LemonModal>
    )
}
