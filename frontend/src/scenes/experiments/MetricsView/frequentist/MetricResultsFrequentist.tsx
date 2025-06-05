import { ExperimentFunnelsQuery, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetric } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { ConfidenceIntervalAxis } from './ConfidenceIntervalAxis'
import { MetricRow } from './MetricRow'

export function MetricResultsFrequentist({
    metrics,
    metricType,
    isSecondary,
}: {
    metrics: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    metricType: InsightType
    isSecondary: boolean
}): JSX.Element {
    return (
        <div className="w-full overflow-x-auto">
            <div className="min-w-[1000px]">
                <div className="rounded bg-[var(--bg-table)]">
                    <ConfidenceIntervalAxis />
                    {metrics.map((_, metricIndex) => {
                        return (
                            <MetricRow
                                key={metricIndex}
                                metrics={metrics}
                                metricIndex={metricIndex}
                                metric={metrics[metricIndex]}
                                metricType={metricType}
                                isSecondary={isSecondary}
                            />
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
