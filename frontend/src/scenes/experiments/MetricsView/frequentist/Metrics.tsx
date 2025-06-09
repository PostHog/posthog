import { IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'

import { experimentLogic } from '../../experimentLogic'
import { MAX_PRIMARY_METRICS, MAX_SECONDARY_METRICS } from '../const'
import { ConfidenceIntervalAxis } from './ConfidenceIntervalAxis'
import { MetricRow } from './MetricRow'

function AddPrimaryMetric(): JSX.Element {
    const { primaryMetricsLengthWithSharedMetrics } = useValues(experimentLogic)
    const { openPrimaryMetricSourceModal } = useActions(experimentLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openPrimaryMetricSourceModal()
            }}
            disabledReason={
                primaryMetricsLengthWithSharedMetrics >= MAX_PRIMARY_METRICS
                    ? `You can only add up to ${MAX_PRIMARY_METRICS} primary metrics.`
                    : undefined
            }
        >
            Add primary metric
        </LemonButton>
    )
}

export function AddSecondaryMetric(): JSX.Element {
    const { secondaryMetricsLengthWithSharedMetrics } = useValues(experimentLogic)
    const { openSecondaryMetricSourceModal } = useActions(experimentLogic)
    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                openSecondaryMetricSourceModal()
            }}
            disabledReason={
                secondaryMetricsLengthWithSharedMetrics >= MAX_SECONDARY_METRICS
                    ? `You can only add up to ${MAX_SECONDARY_METRICS} secondary metrics.`
                    : undefined
            }
        >
            Add secondary metric
        </LemonButton>
    )
}

export function Metrics({ isSecondary }: { isSecondary?: boolean }): JSX.Element {
    const { experiment, getInsightType, metricResults, secondaryMetricResultsNew } = useValues(experimentLogic)

    const variants = experiment?.feature_flag?.filters?.multivariate?.variants
    if (!variants) {
        return <></>
    }

    const results = isSecondary ? secondaryMetricResultsNew : metricResults

    let metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const sharedMetrics = experiment.saved_metrics
        .filter((sharedMetric) => sharedMetric.metadata.type === (isSecondary ? 'secondary' : 'primary'))
        .map((sharedMetric) => ({
            ...sharedMetric.query,
            name: sharedMetric.name,
            sharedMetricId: sharedMetric.saved_metric,
            isSharedMetric: true,
        }))

    if (sharedMetrics) {
        metrics = [...metrics, ...sharedMetrics]
    }

    return (
        <div className="mb-4 -mt-2">
            <div className="flex">
                <div className="w-1/2 pt-5">
                    <div className="inline-flex items-center deprecated-space-x-2 mb-0">
                        <h2 className="mb-0 font-semibold text-lg leading-6">
                            {isSecondary ? 'Secondary metrics' : 'Primary metrics'}
                        </h2>
                        {metrics.length > 0 && (
                            <Tooltip
                                title={
                                    isSecondary
                                        ? 'Secondary metrics capture additional outcomes or behaviors affected by your experiment. They help you understand broader impacts and potential side effects beyond the primary goal.'
                                        : 'Primary metrics represent the main goal of your experiment. They directly measure whether your hypothesis was successful and are the key factor in deciding if the test achieved its primary objective.'
                                }
                            >
                                <IconInfo className="text-secondary text-lg" />
                            </Tooltip>
                        )}
                    </div>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto">
                        {metrics.length > 0 && (
                            <div className="mb-2 mt-4 justify-end">
                                {isSecondary ? <AddSecondaryMetric /> : <AddPrimaryMetric />}
                            </div>
                        )}
                    </div>
                </div>
            </div>
            {metrics.length > 0 ? (
                <div className="w-full overflow-x-auto">
                    <div className="min-w-[1000px]">
                        <div className="rounded bg-[var(--bg-table)]">
                            <ConfidenceIntervalAxis results={results} />
                            {metrics.map((_, metricIndex) => {
                                return (
                                    <MetricRow
                                        key={metricIndex}
                                        metrics={metrics}
                                        metricIndex={metricIndex}
                                        result={results[metricIndex]}
                                        metric={metrics[metricIndex]}
                                        metricType={getInsightType(metrics[0])}
                                        isSecondary={!!isSecondary}
                                    />
                                )
                            })}
                        </div>
                    </div>
                </div>
            ) : (
                <div className="border rounded bg-surface-primary pt-6 pb-8 text-secondary mt-2">
                    <div className="flex flex-col items-center mx-auto deprecated-space-y-3">
                        <IconAreaChart fontSize="30" />
                        <div className="text-sm text-center text-balance max-w-sm">
                            <p>
                                Add up to {MAX_PRIMARY_METRICS} <span>{isSecondary ? 'secondary' : 'primary'}</span>{' '}
                                metrics.
                            </p>
                            <p>
                                {isSecondary
                                    ? 'Secondary metrics provide additional context and help detect unintended side effects.'
                                    : 'Primary metrics represent the main goal of the experiment and directly measure if your hypothesis was successful.'}
                            </p>
                        </div>
                        {isSecondary ? <AddSecondaryMetric /> : <AddPrimaryMetric />}
                    </div>
                </div>
            )}
        </div>
    )
}
