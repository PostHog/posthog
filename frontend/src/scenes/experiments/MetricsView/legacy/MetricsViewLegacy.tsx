import { IconInfo } from '@posthog/icons'
import { LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'

import { EXPERIMENT_MAX_PRIMARY_METRICS, EXPERIMENT_MAX_SECONDARY_METRICS } from '../../constants'
import { credibleIntervalForVariant } from '../../legacyExperimentCalculations'
import { experimentLogic } from '../../experimentLogic'
import { AddPrimaryMetric, AddSecondaryMetric } from '../shared/AddMetric'
import { getNiceTickValues } from '../shared/utils'
import { DeltaChart } from './DeltaChart'

export function MetricsViewLegacy({ isSecondary }: { isSecondary?: boolean }): JSX.Element {
    const {
        experiment,
        getInsightType,
        legacyPrimaryMetricsResults,
        legacySecondaryMetricsResults,
        primaryMetricsResultsErrors,
        secondaryMetricsResultsErrors,
    } = useValues(experimentLogic)

    const variants = experiment?.feature_flag?.filters?.multivariate?.variants
    if (!variants) {
        return <></>
    }

    const results = isSecondary ? legacySecondaryMetricsResults : legacyPrimaryMetricsResults

    const errors = isSecondary ? secondaryMetricsResultsErrors : primaryMetricsResultsErrors
    const hasSomeResults = results?.some((result) => result?.insight)

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

    // Calculate the maximum absolute value across ALL metrics
    const maxAbsValue = Math.max(
        ...metrics.flatMap((metric, metricIndex) => {
            const result = results?.[metricIndex]
            if (!result) {
                return []
            }
            return variants.flatMap((variant) => {
                const insightType = getInsightType(metric)
                const interval = credibleIntervalForVariant(result, variant.key, insightType)
                return interval ? [Math.abs(interval[0] / 100), Math.abs(interval[1] / 100)] : []
            })
        })
    )

    const padding = Math.max(maxAbsValue * 0.05, 0.1)
    const chartBound = maxAbsValue + padding

    const commonTickValues = getNiceTickValues(chartBound)

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
                        {hasSomeResults && !isSecondary && (
                            <>
                                <LemonDivider vertical className="mx-2" />
                                <Tooltip
                                    title={
                                        <div className="p-2">
                                            <p className="mb-4">
                                                Each bar shows how a variant is performing compared to the control (the
                                                gray bar) for this metric, using a{' '}
                                                <strong>95% credible interval.</strong> That means there's a 95% chance
                                                the true difference for that variant falls within this range. The
                                                vertical "0%" line is your baseline:
                                            </p>
                                            <ul className="mb-4 list-disc pl-4">
                                                <li>
                                                    <strong>To the right (green):</strong> The metric is higher (an
                                                    improvement).
                                                </li>
                                                <li>
                                                    <strong>To the left (red):</strong> The metric is lower (a
                                                    decrease).
                                                </li>
                                            </ul>
                                            <p className="mb-4">
                                                The shape of each bar represents the probability distribution. The true
                                                value is more likely to be near the center (where the bar is wider) than
                                                at the edges (where it tapers off).
                                            </p>
                                            <p className="mb-4">
                                                The control (baseline) is always shown in gray. Other bars will be green
                                                or red—or even a mix—depending on whether the change is positive or
                                                negative.
                                            </p>
                                            <img
                                                src="https://res.cloudinary.com/dmukukwp6/image/upload/violin_plot_screenshot_acca775d36.png"
                                                width={700}
                                                className="rounded border object-contain"
                                                alt="How to read metrics"
                                            />
                                        </div>
                                    }
                                >
                                    <span className="text-xs text-secondary cursor-help">How to read</span>
                                </Tooltip>
                            </>
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
                        {metrics.map((metric, metricIndex) => {
                            const result = results?.[metricIndex]
                            const isFirstMetric = metricIndex === 0

                            return (
                                <div
                                    key={metricIndex}
                                    className={`w-full border border-primary bg-light ${
                                        metrics.length === 1
                                            ? 'rounded'
                                            : isFirstMetric
                                            ? 'rounded-t'
                                            : metricIndex === metrics.length - 1
                                            ? 'rounded-b'
                                            : ''
                                    }`}
                                >
                                    <DeltaChart
                                        isSecondary={!!isSecondary}
                                        result={result}
                                        error={errors?.[metricIndex]}
                                        variants={variants}
                                        metricType={getInsightType(metric)}
                                        metricIndex={metricIndex}
                                        isFirstMetric={isFirstMetric}
                                        metric={metric}
                                        tickValues={commonTickValues}
                                        chartBound={chartBound}
                                    />
                                </div>
                            )
                        })}
                    </div>
                </div>
            ) : (
                <div className="border rounded bg-surface-primary pt-6 pb-8 text-secondary mt-2">
                    <div className="flex flex-col items-center mx-auto deprecated-space-y-3">
                        <IconAreaChart fontSize="30" />
                        <div className="text-sm text-center text-balance max-w-sm">
                            <p>
                                {`Add up to ${
                                    isSecondary ? EXPERIMENT_MAX_SECONDARY_METRICS : EXPERIMENT_MAX_PRIMARY_METRICS
                                } ${isSecondary ? 'secondary' : 'primary'} metrics.`}
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
