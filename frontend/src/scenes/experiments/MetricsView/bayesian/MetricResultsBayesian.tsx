import { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { DeltaChart } from '../DeltaChart'

export function MetricResultsBayesian({
    metrics,
    results,
    errors,
    variants,
    metricType,
    isSecondary,
    commonTickValues,
    chartBound,
}: {
    metrics: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    results: any[]
    errors: any[]
    variants: any[]
    metricType: InsightType
    isSecondary: boolean
    commonTickValues: number[]
    chartBound: number
}): JSX.Element {
    return (
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
                                metricType={metricType}
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
    )
}
