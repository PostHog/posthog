import { LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { humanFriendlyNumber } from 'lib/utils'

import { experimentLogic } from '../experimentLogic'
import { EventSelectorStep } from './EventSelectorStep'
import { MetricSelectorStep } from './MetricSelectorStep'
import { ConversionRateInputType, runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'
import { RunningTimeCalculatorModalFooter } from './RunningTimeCalculatorModalFooter'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'
import { modalsLogic } from '../modalsLogic'
export function RunningTimeCalculatorModal(): JSX.Element {
    /**
     * Modal open/close is controlled from parent component.
     * This is a candidate for props (onClose, onSave)
     */
    const { experimentId } = useValues(experimentLogic)
    const { isCalculateRunningTimeModalOpen } = useValues(modalsLogic)
    const {
        // Experiment Object
        experiment,
        // Running Time Calculator Object. Saved inside the experiment parameters.
        minimumDetectableEffect,
        recommendedSampleSize,
        recommendedRunningTime,
        exposureEstimateConfig,
        // FunnelQuery for unique users loading state
        metricResultLoading,
        // Queried value depending on the exposureEstimateConfig
        uniqueUsers,
    } = useValues(runningTimeCalculatorLogic({ experimentId }))

    const { updateExperiment } = useActions(experimentLogic)
    const { setMinimumDetectableEffect, setExposureEstimateConfig } = useActions(
        runningTimeCalculatorLogic({ experimentId })
    )
    const { closeCalculateRunningTimeModal } = useActions(modalsLogic)

    return (
        <LemonModal
            isOpen={isCalculateRunningTimeModalOpen}
            onClose={closeCalculateRunningTimeModal}
            width={700}
            title="Calculate estimated running time"
            footer={
                <RunningTimeCalculatorModalFooter
                    onClose={closeCalculateRunningTimeModal}
                    onSave={() => {
                        updateExperiment({
                            parameters: {
                                ...experiment?.parameters,
                                exposure_estimate_config: exposureEstimateConfig,
                                recommended_running_time: recommendedRunningTime,
                                recommended_sample_size: recommendedSampleSize || undefined,
                                minimum_detectable_effect: minimumDetectableEffect || undefined,
                            },
                        })
                        closeCalculateRunningTimeModal()
                    }}
                />
            }
        >
            <EventSelectorStep
                exposureEstimateConfig={exposureEstimateConfig}
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
                    onChangeMetric={(metric) =>
                        setExposureEstimateConfig({
                            ...exposureEstimateConfig,
                            metric,
                        })
                    }
                    onChangeFunnelConversionRateType={(type) =>
                        setExposureEstimateConfig({
                            ...exposureEstimateConfig,
                            conversionRateInputType: type,
                        })
                    }
                />
            )}

            <div className="deprecated-space-y-6">
                {!metricResultLoading && uniqueUsers !== null && (
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
