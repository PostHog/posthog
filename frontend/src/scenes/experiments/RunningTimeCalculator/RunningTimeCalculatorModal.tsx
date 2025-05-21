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
import { useExposureEstimateConfig } from './hooks/useExposureEstimateConfig'
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
    automaticConversionRate: null,
    uniqueUsers: null,
    averageEventsPerUser: null,
    averagePropertyValuePerUser: null,
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
    const { experimentBaseline, experimentBaselineLoading } = useValues(runningTimeCalculatorLogic({ experimentId }))
    const { loadExperimentBaseline } = useActions(runningTimeCalculatorLogic({ experimentId }))

    const {
        config: exposureEstimateConfig,
        isDirty,
        patchExposureConfig,
        setExposureConfig,
        setIsDirty,
    } = useExposureEstimateConfig(
        experiment.parameters.exposure_estimate_config ?? defaultExposureEstimateConfig,
        experiment,
        loadExperimentBaseline
    )

    /**
     * We track this outside of the exposure estimate config
     * because we are saving it on experiment parameters.
     */
    const [minimumDetectableEffect, setMinimumDetectableEffect] = useState(
        experiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE
    )

    const variance = calculateVariance(
        exposureEstimateConfig?.metric as ExperimentMetric,
        experimentBaseline?.averageEventsPerUser ?? 0,
        experimentBaseline?.averagePropertyValuePerUser ?? 0
    )

    // Only calculate new values if we have exposure estimate and no saved values
    const calculatedSampleSize =
        !isDirty && experimentBaseline && exposureEstimateConfig?.metric
            ? calculateRecommendedSampleSize(
                  exposureEstimateConfig.metric,
                  minimumDetectableEffect,
                  variance ?? 0,
                  experimentBaseline.averageEventsPerUser ?? 0,
                  experimentBaseline.averagePropertyValuePerUser ?? 0,
                  experimentBaseline.automaticConversionRateDecimal ?? 0,
                  experimentBaseline.manualConversionRate ?? 0,
                  exposureEstimateConfig.conversionRateInputType,
                  metrics.length
              )
            : null

    const calculatedRunningTime =
        !isDirty && experimentBaseline?.uniqueUsers && calculatedSampleSize
            ? calculatedSampleSize / (experimentBaseline.uniqueUsers / TIMEFRAME_HISTORICAL_DATA_DAYS)
            : null

    // Use saved values if they exist and the form is not dirty
    const recommendedSampleSize = !isDirty ? experiment.parameters.recommended_sample_size : calculatedSampleSize

    const recommendedRunningTime = !isDirty ? experiment.parameters.recommended_running_time : calculatedRunningTime

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
                        /**
                         * We save the experiment baseline as part of the diaglog config
                         * so we can allow for edits.
                         */
                        onSave(
                            {
                                ...exposureEstimateConfig,
                                ...experimentBaseline,
                            },
                            minimumDetectableEffect,
                            recommendedSampleSize ?? Infinity,
                            recommendedRunningTime ?? Infinity
                        )
                    }
                />
            }
        >
            <EventSelectorStep
                exposureEstimateConfig={exposureEstimateConfig}
                onSetFilter={(filter) => {
                    patchExposureConfig({
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
                }}
            />
            {metrics.length > 0 && exposureEstimateConfig && (
                <MetricSelectorStep
                    experimentId={experimentId}
                    experimentMetrics={metrics as ExperimentMetric[]}
                    exposureEstimateConfig={exposureEstimateConfig}
                    onChangeMetric={(metric) => patchExposureConfig({ metric })}
                    onChangeFunnelConversionRateType={(type) => patchExposureConfig({ conversionRateInputType: type })}
                    onChangeManualConversionRate={(rate) => patchExposureConfig({ manualConversionRate: rate })}
                />
            )}
            <div className="deprecated-space-y-6">
                {!experimentBaselineLoading && experimentBaseline && (
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
                        {recommendedSampleSize && recommendedRunningTime && (
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
