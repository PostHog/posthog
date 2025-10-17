import { useActions, useValues } from 'kea'

import { LemonSelect, LemonTag, Spinner } from '@posthog/lemon-ui'

import {
    ExperimentMetric,
    NodeKind,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
} from '~/queries/schema/schema-general'

import { MetricTitle } from '../MetricsView/shared/MetricTitle'
import { experimentLogic } from '../experimentLogic'
import { FunnelMetricDataPanel } from './FunnelMetricDataPanel'
import { MeanMetricDataPanel } from './MeanMetricDataPanel'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'
import { ConversionRateInputType, runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'

type MetricOption = {
    metric: ExperimentMetric
    uuid: string
    isSharedMetric: boolean
    name: string | undefined
}

export const MetricSelectorStep = ({
    onChangeMetric,
    onChangeFunnelConversionRateType,
}: {
    onChangeMetric: (metric: ExperimentMetric) => void
    onChangeFunnelConversionRateType: (type: ConversionRateInputType) => void
}): JSX.Element => {
    const { experimentId } = useValues(experimentLogic)

    const { experiment, metric, metricUuid, metricResultLoading } = useValues(
        runningTimeCalculatorLogic({ experimentId })
    )
    const { setMetricUuid } = useActions(runningTimeCalculatorLogic({ experimentId }))

    // Create combined array of metrics and saved metrics
    const metricOptions: MetricOption[] = [
        // Regular metrics
        ...experiment.metrics
            .filter((metric) => metric.uuid)
            .map((metric) => ({
                metric: metric as ExperimentMetric,
                uuid: metric.uuid!,
                isSharedMetric: false,
                name: undefined,
            })),
        // Shared metrics with primary type
        ...experiment.saved_metrics
            .filter((sharedMetric) => sharedMetric.metadata.type === 'primary')
            .map((sharedMetric) => {
                // Ensure the shared metric query is an ExperimentMetric type
                if (
                    sharedMetric.query &&
                    sharedMetric.query.uuid &&
                    (sharedMetric.query.kind === NodeKind.ExperimentMetric ||
                        sharedMetric.query.metric_type !== undefined)
                ) {
                    return {
                        metric: sharedMetric.query as ExperimentMetric,
                        uuid: sharedMetric.query.uuid,
                        isSharedMetric: true,
                        name: sharedMetric.name,
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
                <div className="card-secondary mb-2">Experiment metric</div>
                <LemonSelect
                    options={metricOptions.map((option, index) => ({
                        label: (
                            <div className="cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis flex-grow flex items-center">
                                <span className="mr-1">{index + 1}.</span>
                                {option.name ? (
                                    <span className="max-w-56 truncate">{option.name}</span>
                                ) : (
                                    <MetricTitle metric={option.metric} />
                                )}
                                {option.isSharedMetric && (
                                    <span className="ml-1">
                                        <LemonTag>Shared</LemonTag>
                                    </span>
                                )}
                            </div>
                        ),
                        value: option.uuid,
                    }))}
                    value={metricUuid}
                    onChange={(value) => {
                        if (value !== null) {
                            setMetricUuid(value)
                            const selectedOption = metricOptions.find((option) => option.uuid === value)
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
                    {metric && isExperimentMeanMetric(metric) && <MeanMetricDataPanel />}
                    {metric && isExperimentFunnelMetric(metric) && (
                        <FunnelMetricDataPanel onChangeType={onChangeFunnelConversionRateType} />
                    )}
                </div>
            )}
        </RunningTimeCalculatorModalStep>
    )
}
