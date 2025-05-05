import { LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { humanFriendlyNumber } from 'lib/utils'

import type { Experiment } from '~/types'

import { EventSelectorStep } from './EventSelectorStep'
import { MetricSelectorStep } from './MetricSelectorStep'
import {
    ConversionRateInputType,
    ExposureEstimateConfig,
    runningTimeCalculatorLogic,
} from './runningTimeCalculatorLogic'
import { RunningTimeCalculatorModalFooter } from './RunningTimeCalculatorModalFooter'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'

type RunningTimeCalculatorModalProps = {
    experimentId: Experiment['id']
    isOpen: boolean
    onClose: () => void
    onSave: (
        exposureEstimateConfig: ExposureEstimateConfig | null,
        minimumDetectableEffect: number,
        recommendedSampleSize: number,
        recommendedRunningTime: number
    ) => void
}

export function RunningTimeCalculatorModal({
    experimentId,
    isOpen,
    onClose,
    onSave,
}: RunningTimeCalculatorModalProps): JSX.Element {
    const {
        /**
         * Exposure Estimate Config Modal State.
         * Without kea, this would be a prop.
         */
        exposureEstimateConfig,
        // Running Time Calculator Object. Saved inside the experiment parameters.
        minimumDetectableEffect,
        recommendedSampleSize,
        recommendedRunningTime,
        // FunnelQuery for unique users loading state
        metricResultLoading,
        // Queried value depending on the exposureEstimateConfig
        uniqueUsers,
    } = useValues(runningTimeCalculatorLogic({ experimentId }))

    const { setMinimumDetectableEffect, setExposureEstimateConfig } = useActions(
        runningTimeCalculatorLogic({ experimentId })
    )

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
                            recommendedSampleSize ?? 0,
                            recommendedRunningTime ?? 0
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
