import { LemonSelect, LemonTag, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'
import { MetricTitle } from '../MetricsView/shared/MetricTitle'
import { FunnelMetricDataPanel } from './FunnelMetricDataPanel'
import { MeanMetricDataPanel } from './MeanMetricDataPanel'
import { ConversionRateInputType, runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'

type MetricOption = {
    metric: ExperimentMetric
    index: number
    isSharedMetric: boolean
}

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

    // Create combined array of metrics and saved metrics
    const metricOptions: MetricOption[] = [
        // Regular metrics
        ...experiment.metrics.map((metric, index) => ({
            metric: metric as ExperimentMetric,
            index,
            isSharedMetric: false,
        })),
        // Shared metrics with primary type
        ...experiment.saved_metrics
            .filter((sharedMetric) => sharedMetric.metadata.type === 'primary')
            .map((sharedMetric, index) => {
                // Ensure the shared metric query is an ExperimentMetric type
                if (
                    sharedMetric.query &&
                    (sharedMetric.query.kind === NodeKind.ExperimentMetric ||
                        sharedMetric.query.metric_type !== undefined)
                ) {
                    return {
                        metric: sharedMetric.query as ExperimentMetric,
                        index: experiment.metrics.length + index,
                        isSharedMetric: true,
                    }
                }
                return null
            })
            .filter((option): option is MetricOption => option !== null),
    ]

    return (
        <RunningTimeCalculatorModalStep
            stepNumber={2}
            title="Select a metric"
            description="Choose a metric to analyze. We'll use historical data from this metric to estimate the experiment duration."
        >
            <div className="mb-4">
                <div className="deprecated-label mb-2">Experiment metric</div>
                <LemonSelect
                    options={metricOptions.map((option, index) => ({
                        label: (
                            <div className="cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis flex-grow flex items-center">
                                <span className="mr-1">{index + 1}.</span>
                                <MetricTitle metric={option.metric} />
                                {option.isSharedMetric && (
                                    <span className="ml-1">
                                        <LemonTag>Shared</LemonTag>
                                    </span>
                                )}
                            </div>
                        ),
                        value: option.index,
                    }))}
                    value={metricIndex}
                    onChange={(value) => {
                        if (value !== null) {
                            setMetricIndex(value)
                            const selectedOption = metricOptions.find((option) => option.index === value)
                            if (selectedOption) {
                                onChangeMetric(selectedOption.metric)
                            }
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
