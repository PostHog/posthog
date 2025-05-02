import { LemonSelect, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

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

    const { experiment, metric, metricIndex, metricResultLoading } = useValues(
        runningTimeCalculatorLogic({ experimentId })
    )

    const { setMetricIndex } = useActions(runningTimeCalculatorLogic({ experimentId }))

    return (
        <RunningTimeCalculatorModalStep
            stepNumber={2}
            title="Select a Metric"
            description="Choose a metric to analyze. We'll use historical data from this metric to estimate the experiment duration."
        >
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
                            /**
                             * Instead of using the metric index, we should be using an unique id.
                             * This could lead to issues if the metrics change after saving this value.
                             */
                            onChangeMetric(experiment.metrics[value] as ExperimentMetric)
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
                    {(metric as ExperimentMetric)?.metric_type === ExperimentMetricType.MEAN && <MeanMetricDataPanel />}
                    {(metric as ExperimentMetric)?.metric_type === ExperimentMetricType.FUNNEL && (
                        <FunnelMetricDataPanel onChangeType={onChangeFunnelConversionRateType} />
                    )}
                </div>
            )}
        </RunningTimeCalculatorModalStep>
    )
}
