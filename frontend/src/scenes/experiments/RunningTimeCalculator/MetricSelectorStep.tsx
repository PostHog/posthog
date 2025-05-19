import { LemonSelect, LemonTag, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import React from 'react'

import { ExperimentMetric, ExperimentMetricType } from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'
import { MetricTitle } from '../MetricsView/MetricTitle'
import { FunnelMetricDataPanel } from './FunnelMetricDataPanel'
import { MeanMetricDataPanel } from './MeanMetricDataPanel'
import { ConversionRateInputType, runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'

export const MetricSelectorStep = ({
    onChangeMetric,
    onChangeFunnelConversionRateType,
}: {
    onChangeMetric: (metric: ExperimentMetric) => void
    onChangeFunnelConversionRateType: (type: ConversionRateInputType) => void
}): JSX.Element => {
    const { experimentId } = useValues(experimentLogic)

    const { experiment, metric, metricResultLoading } = useValues(runningTimeCalculatorLogic({ experimentId }))
    const { setSelectedMetric } = useActions(runningTimeCalculatorLogic({ experimentId }))

    // Create combined array of metrics (both regular and shared)
    const availableMetrics = React.useMemo(() => {
        const regularMetrics = experiment.metrics.map((m) => m as ExperimentMetric)
        const sharedMetrics = experiment.saved_metrics
            .filter((m) => m.metadata.type === 'primary')
            .map((m) => m.query as ExperimentMetric)
            .filter(Boolean)

        return [...regularMetrics, ...sharedMetrics]
    }, [experiment.metrics, experiment.saved_metrics])

    // Helper function to determine if a metric is a shared metric
    const isSharedMetric = (metricToCheck: ExperimentMetric): boolean => {
        return experiment.saved_metrics.some((m) => m.query === metricToCheck)
    }

    return (
        <RunningTimeCalculatorModalStep
            stepNumber={2}
            title="Select a metric"
            description="Choose a metric to analyze. We'll use historical data from this metric to estimate the experiment duration."
        >
            <div className="mb-4">
                <div className="card-secondary mb-2">Experiment metric</div>
                <LemonSelect
                    options={availableMetrics.map((metricOption, index: number) => ({
                        label: (
                            <div className="cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis flex-grow flex items-center">
                                <span className="mr-1">{index + 1}.</span>
                                <MetricTitle metric={metricOption} />
                                {isSharedMetric(metricOption) && (
                                    <span className="ml-1">
                                        <LemonTag>Shared</LemonTag>
                                    </span>
                                )}
                            </div>
                        ),
                        value: index, // Use index as the value for LemonSelect
                    }))}
                    value={availableMetrics.findIndex((m) => JSON.stringify(m) === JSON.stringify(metric))}
                    onChange={(value) => {
                        if (value !== null && value >= 0 && value < availableMetrics.length) {
                            const selectedMetric = availableMetrics[value]
                            setSelectedMetric(selectedMetric)
                            onChangeMetric(selectedMetric)
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
                    {metric?.metric_type === ExperimentMetricType.MEAN && <MeanMetricDataPanel />}
                    {metric?.metric_type === ExperimentMetricType.FUNNEL && (
                        <FunnelMetricDataPanel onChangeType={onChangeFunnelConversionRateType} />
                    )}
                </div>
            )}
        </RunningTimeCalculatorModalStep>
    )
}
