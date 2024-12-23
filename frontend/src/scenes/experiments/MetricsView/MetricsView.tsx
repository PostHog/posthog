import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'

import { experimentLogic, getDefaultFunnelsMetric } from '../experimentLogic'
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
    const { experiment } = useValues(experimentLogic)
    const { setExperiment, openPrimaryMetricModal } = useActions(experimentLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                const newMetrics = [...experiment.metrics, getDefaultFunnelsMetric()]
                setExperiment({
                    metrics: newMetrics,
                })
                openPrimaryMetricModal(newMetrics.length - 1)
            }}
            disabledReason={
                experiment.metrics.length >= MAX_PRIMARY_METRICS
                    ? `You can only add up to ${MAX_PRIMARY_METRICS} primary metrics.`
                    : undefined
            }
        >
            Add primary metric
        </LemonButton>
    )
}

export function AddSecondaryMetric(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { setExperiment, openSecondaryMetricModal } = useActions(experimentLogic)
    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                const newMetricsSecondary = [...experiment.metrics_secondary, getDefaultFunnelsMetric()]
                setExperiment({
                    metrics_secondary: newMetricsSecondary,
                })
                openSecondaryMetricModal(newMetricsSecondary.length - 1)
            }}
            disabledReason={
                experiment.metrics_secondary.length >= MAX_SECONDARY_METRICS
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
        getMetricType,
        getSecondaryMetricType,
        metricResults,
        secondaryMetricResults,
        primaryMetricsResultErrors,
        secondaryMetricsResultErrors,
        credibleIntervalForVariant,
    } = useValues(experimentLogic)

    const variants = experiment.parameters.feature_flag_variants
    const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const results = isSecondary ? secondaryMetricResults : metricResults
    const errors = isSecondary ? secondaryMetricsResultErrors : primaryMetricsResultErrors

    // Calculate the maximum absolute value across ALL metrics
    const maxAbsValue = Math.max(
        ...metrics.flatMap((_, metricIndex) => {
            const result = results?.[metricIndex]
            if (!result) {
                return []
            }
            return variants.flatMap((variant) => {
                const metricType = isSecondary ? getSecondaryMetricType(metricIndex) : getMetricType(metricIndex)
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
                    <div className="inline-flex space-x-2 mb-0">
                        <h2 className="mb-1 font-semibold text-lg">
                            {isSecondary ? 'Secondary metrics' : 'Primary metrics'}
                        </h2>
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
                                        metricType={
                                            isSecondary
                                                ? getSecondaryMetricType(metricIndex)
                                                : getMetricType(metricIndex)
                                        }
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
