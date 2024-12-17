import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconAreaChart } from 'lib/lemon-ui/icons'

import { experimentLogic, getDefaultFunnelsMetric } from '../experimentLogic'
import { MAX_PRIMARY_METRICS } from './const'
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

function AddMetric({
    metrics,
    setExperiment,
    openPrimaryMetricModal,
}: {
    metrics: any[]
    setExperiment: (payload: { metrics: any[] }) => void
    openPrimaryMetricModal: (index: number) => void
}): JSX.Element {
    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="xsmall"
            onClick={() => {
                const newMetrics = [...metrics, getDefaultFunnelsMetric()]
                setExperiment({
                    metrics: newMetrics,
                })
                openPrimaryMetricModal(newMetrics.length - 1)
            }}
            disabledReason={
                metrics.length >= MAX_PRIMARY_METRICS
                    ? `You can only add up to ${MAX_PRIMARY_METRICS} primary metrics.`
                    : undefined
            }
        >
            Add metric
        </LemonButton>
    )
}

export function MetricsView(): JSX.Element {
    const { experiment, getMetricType, metricResults, primaryMetricsResultErrors, credibleIntervalForVariant } =
        useValues(experimentLogic)
    const { setExperiment, openPrimaryMetricModal } = useActions(experimentLogic)

    const variants = experiment.parameters.feature_flag_variants
    const metrics = experiment.metrics || []

    // Calculate the maximum absolute value across ALL metrics
    const maxAbsValue = Math.max(
        ...metrics.flatMap((_, metricIndex) => {
            const result = metricResults?.[metricIndex]
            if (!result) {
                return []
            }
            return variants.flatMap((variant) => {
                const interval = credibleIntervalForVariant(result, variant.key, getMetricType(metricIndex))
                return interval ? [Math.abs(interval[0] / 100), Math.abs(interval[1] / 100)] : []
            })
        })
    )

    const padding = Math.max(maxAbsValue * 0.05, 0.02)
    const chartBound = maxAbsValue + padding

    const commonTickValues = getNiceTickValues(chartBound)

    return (
        <div className="mb-4">
            <div className="flex">
                <div className="w-1/2 pt-5">
                    <div className="inline-flex space-x-2 mb-0">
                        <h2 className="mb-1 font-semibold text-lg">Primary metrics</h2>
                    </div>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto">
                        <div className="mb-2 mt-4 justify-end">
                            <AddMetric
                                metrics={metrics}
                                setExperiment={setExperiment}
                                openPrimaryMetricModal={openPrimaryMetricModal}
                            />
                        </div>
                    </div>
                </div>
            </div>
            {metrics.length > 0 ? (
                <div className="w-full overflow-x-auto">
                    <div className="min-w-[800px]">
                        {metrics.map((metric, metricIndex) => {
                            const result = metricResults?.[metricIndex]
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
                                        result={result}
                                        error={primaryMetricsResultErrors?.[metricIndex]}
                                        variants={variants}
                                        metricType={getMetricType(metricIndex)}
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
                            Add up to {MAX_PRIMARY_METRICS} primary metrics to monitor side effects of your experiment.
                        </div>
                        <AddMetric
                            metrics={metrics}
                            setExperiment={setExperiment}
                            openPrimaryMetricModal={openPrimaryMetricModal}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
