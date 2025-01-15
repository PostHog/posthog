import { IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'

import { experimentLogic } from '../experimentLogic'
import { MAX_PRIMARY_METRICS, MAX_SECONDARY_METRICS } from './const'
import { DeltaChart } from './DeltaChart'

// Helper function to find nice round numbers for ticks
export function getNiceTickValues(maxAbsValue: number): number[] {
    // Round up maxAbsValue to ensure we cover all values
    maxAbsValue = Math.ceil(maxAbsValue * 10) / 10

    const magnitude = Math.floor(Math.log10(maxAbsValue))
    const power = Math.pow(10, magnitude)

    let baseUnit
    const normalizedMax = maxAbsValue / power
    if (normalizedMax <= 1) {
        baseUnit = 0.2 * power
    } else if (normalizedMax <= 2) {
        baseUnit = 0.5 * power
    } else if (normalizedMax <= 5) {
        baseUnit = 1 * power
    } else {
        baseUnit = 2 * power
    }

    // Calculate how many baseUnits we need to exceed maxAbsValue
    const unitsNeeded = Math.ceil(maxAbsValue / baseUnit)

    // Determine appropriate number of decimal places based on magnitude
    const decimalPlaces = Math.max(0, -magnitude + 1)

    const ticks: number[] = []
    for (let i = -unitsNeeded; i <= unitsNeeded; i++) {
        // Round each tick value to avoid floating point precision issues
        const tickValue = Number((baseUnit * i).toFixed(decimalPlaces))
        ticks.push(tickValue)
    }
    return ticks
}

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

export function MetricsView({ isSecondary }: { isSecondary?: boolean }): JSX.Element {
    const {
        experiment,
        _getMetricType,
        metricResults,
        secondaryMetricResults,
        primaryMetricsResultErrors,
        secondaryMetricsResultErrors,
        credibleIntervalForVariant,
    } = useValues(experimentLogic)

    const variants = experiment?.feature_flag?.filters?.multivariate?.variants
    if (!variants) {
        return <></>
    }
    const results = isSecondary ? secondaryMetricResults : metricResults
    const errors = isSecondary ? secondaryMetricsResultErrors : primaryMetricsResultErrors
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
                const metricType = _getMetricType(metric)
                const interval = credibleIntervalForVariant(result, variant.key, metricType)
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
                    <div className="inline-flex items-center space-x-2 mb-0">
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
                                <IconInfo className="text-muted-alt text-lg" />
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
                                                The <strong>width of the bar</strong> represents uncertainty. A{' '}
                                                <strong>narrower bar</strong> means we're more confident in that result,
                                                while a <strong>wider bar</strong> means it could shift either way.
                                            </p>
                                            <p className="mb-4">
                                                The control (baseline) is always shown in gray. Other bars will be green
                                                or red—or even a mix—depending on whether the change is positive or
                                                negative.
                                            </p>
                                            <img
                                                src="https://res.cloudinary.com/dmukukwp6/image/upload/Screenshot_2024_12_28_at_21_09_55_8828faf254.png"
                                                width={700}
                                                className="rounded border object-contain"
                                                alt="How to read metrics"
                                            />
                                        </div>
                                    }
                                >
                                    <span className="text-xs text-muted-alt cursor-help">How to read</span>
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
                                    className={`w-full border border-border bg-light ${
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
                                        metricType={_getMetricType(metric)}
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
                <div className="border rounded bg-bg-light pt-6 pb-8 text-muted mt-2">
                    <div className="flex flex-col items-center mx-auto space-y-3">
                        <IconAreaChart fontSize="30" />
                        <div className="text-sm text-center text-balance">
                            Add up to {MAX_PRIMARY_METRICS} {isSecondary ? 'secondary' : 'primary'} metrics.
                        </div>
                        {isSecondary ? <AddSecondaryMetric /> : <AddPrimaryMetric />}
                    </div>
                </div>
            )}
        </div>
    )
}
