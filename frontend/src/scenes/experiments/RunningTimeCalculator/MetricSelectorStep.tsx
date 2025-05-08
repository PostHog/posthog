import { LemonSelect, Spinner } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { useState } from 'react'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { ExperimentMetricType } from '~/queries/schema/schema-general'
import type { ExperimentIdType } from '~/types'

import { MetricTitle } from '../MetricsView/MetricTitle'
import { FunnelMetricDataPanel } from './FunnelMetricDataPanel'
import { MeanMetricDataPanel } from './MeanMetricDataPanel'
import type { ConversionRateInputType, ExposureEstimateConfig } from './runningTimeCalculatorLogic'
import { runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'

type MetricSelectorStepProps = {
    /**
     * We need the experimentId to get the result of the
     */
    experimentId: ExperimentIdType
    experimentMetrics: ExperimentMetric[]
    exposureEstimateConfig: ExposureEstimateConfig
    onChangeMetric: (metric: ExperimentMetric) => void
    onChangeFunnelConversionRateType: (type: ConversionRateInputType) => void
}

export const MetricSelectorStep = ({
    experimentId,
    experimentMetrics,
    exposureEstimateConfig,
    onChangeMetric,
    onChangeFunnelConversionRateType,
}: MetricSelectorStepProps): JSX.Element => {
    /**
     * We limit Kea to only load the exposure estimate for the selected metric.
     * This is a candidate for a custom hook.
     */
    const { exposureEstimate, exposureEstimateLoading } = useValues(runningTimeCalculatorLogic({ experimentId }))

    /**
     * Find the index of the metric in the experiment metrics.
     */
    const defaultMetricIndex = experimentMetrics.findIndex((m) => equal(m, exposureEstimateConfig.metric))
    const [metricIndex, setMetricIndex] = useState<number>(defaultMetricIndex)

    return (
        <RunningTimeCalculatorModalStep
            stepNumber={2}
            title="Select a metric"
            description="Choose a metric to analyze. We'll use historical data from this metric to estimate the experiment duration."
        >
            <div className="mb-4">
                <div className="card-secondary mb-2">Experiment metric</div>
                <LemonSelect
                    options={experimentMetrics.map((metric, index) => ({
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
                            /**
                             * The metric index is local state of this component,
                             * while the metric is a prop, with state managed externally.
                             */
                            setMetricIndex(value)
                            /**
                             * Instead of using the metric index, we should be using an unique id.
                             * This could lead to issues if the metrics change after saving this value.
                             */
                            onChangeMetric(experimentMetrics[value])
                        }
                    }}
                />
            </div>
            {exposureEstimateLoading ? (
                <div className="border-t pt-2">
                    <div className="h-[100px] flex items-center justify-center">
                        <Spinner className="text-3xl transform -translate-y-[-10px]" />
                    </div>
                </div>
            ) : (
                <div className="border-t pt-2">
                    {exposureEstimateConfig.metric?.metric_type === ExperimentMetricType.MEAN && (
                        <MeanMetricDataPanel
                            metric={exposureEstimateConfig.metric as ExperimentMetric}
                            uniqueUsers={exposureEstimate?.uniqueUsers ?? exposureEstimateConfig.uniqueUsers}
                            averageEventsPerUser={exposureEstimate?.averageEventsPerUser} //TODO: This needs saving on the exposure estimate config
                            averagePropertyValuePerUser={exposureEstimate?.averagePropertyValuePerUser} //TODO: This needs saving on the exposure estimate config
                        />
                    )}
                    {exposureEstimateConfig.metric?.metric_type === ExperimentMetricType.FUNNEL && (
                        <FunnelMetricDataPanel
                            uniqueUsers={exposureEstimate?.uniqueUsers ?? exposureEstimateConfig.uniqueUsers}
                            conversionRateInputType={exposureEstimateConfig.conversionRateInputType}
                            automaticConversionRateDecimal={exposureEstimate?.automaticConversionRateDecimal}
                            manualConversionRate={exposureEstimate?.manualConversionRate}
                            onChangeType={onChangeFunnelConversionRateType}
                            onChangeManualConversionRate={() => {}}
                        />
                    )}
                </div>
            )}
        </RunningTimeCalculatorModalStep>
    )
}
