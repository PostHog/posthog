import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'

import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'

import { experimentLogic } from '../../experimentLogic'
import { AddPrimaryMetric, AddSecondaryMetric } from '../shared/AddMetric'
import { MAX_PRIMARY_METRICS } from '../shared/const'
import { ConfidenceIntervalAxis } from './ConfidenceIntervalAxis'
import { MetricRow } from './MetricRow'
import { ResultDetails } from './ResultDetails'

export function Metrics({ isSecondary }: { isSecondary?: boolean }): JSX.Element {
    const {
        experiment,
        getInsightType,
        primaryMetricsResults,
        secondaryMetricsResults,
        secondaryMetricsResultsErrors,
        primaryMetricsResultsErrors,
        hasMinimumExposureForResults,
    } = useValues(experimentLogic)

    const variants = experiment?.feature_flag?.filters?.multivariate?.variants
    if (!variants) {
        return <></>
    }

    const results = isSecondary ? secondaryMetricsResults : primaryMetricsResults
    const errors = isSecondary ? secondaryMetricsResultsErrors : primaryMetricsResultsErrors

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

    // Calculate shared chartRadius across all metrics
    const maxAbsValue = Math.max(
        ...results.flatMap((result: NewExperimentQueryResponse) => {
            const variantResults = result?.variant_results || []
            return variantResults.flatMap((variant: any) => {
                const interval = variant.confidence_interval
                return interval ? [Math.abs(interval[0]), Math.abs(interval[1])] : []
            })
        })
    )

    const axisMargin = Math.max(maxAbsValue * 0.05, 0.1)
    const chartRadius = maxAbsValue + axisMargin

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
                <>
                    <div className="w-full overflow-x-auto">
                        <div className="min-w-[1000px]">
                            <div className="rounded bg-[var(--bg-table)]">
                                <ConfidenceIntervalAxis chartRadius={chartRadius} />
                                {metrics.map((metric, metricIndex) => {
                                    const result = results[metricIndex]

                                    return (
                                        <div key={metricIndex}>
                                            <MetricRow
                                                metrics={metrics}
                                                metricIndex={metricIndex}
                                                result={results[metricIndex]}
                                                metric={metric}
                                                metricType={getInsightType(metric)}
                                                isSecondary={!!isSecondary}
                                                chartRadius={chartRadius}
                                                error={errors[metricIndex]}
                                            />
                                            {metrics.length === 1 && result && hasMinimumExposureForResults && (
                                                <div className="mt-2">
                                                    <ResultDetails
                                                        metric={metric as ExperimentMetric}
                                                        result={{
                                                            ...results[metricIndex],
                                                            metric: metric as ExperimentMetric,
                                                        }}
                                                        experiment={experiment}
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                    </div>
                </>
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
