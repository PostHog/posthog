import { useActions, useValues } from 'kea'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NewExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { experimentLogic } from '../../experimentLogic'
import { type ExperimentVariantResult, getVariantInterval } from '../shared/utils'
import { MetricRowGroup } from './MetricRowGroup'
import { TableHeader } from './TableHeader'

interface MetricsTableProps {
    metrics: ExperimentMetric[]
    results: NewExperimentQueryResponse[]
    errors: any[]
    isSecondary: boolean
    getInsightType: (metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery) => InsightType
    showDetailsModal?: boolean
}

export function MetricsTable({
    metrics,
    results,
    errors,
    isSecondary,
    getInsightType,
    showDetailsModal = true,
}: MetricsTableProps): JSX.Element {
    const { experiment, hasMinimumExposureForResults } = useValues(experimentLogic)
    const { duplicateMetric, updateExperimentMetrics } = useActions(experimentLogic)

    // Calculate shared axisRange across all metrics
    const maxAbsValue = Math.max(
        ...results.flatMap((result: NewExperimentQueryResponse) => {
            const variantResults = result?.variant_results || []
            return variantResults.flatMap((variant: ExperimentVariantResult) => {
                const interval = getVariantInterval(variant)
                return interval ? [Math.abs(interval[0]), Math.abs(interval[1])] : []
            })
        })
    )

    const axisMargin = Math.max(maxAbsValue * 0.05, 0.1)
    const axisRange = maxAbsValue + axisMargin

    if (metrics.length === 0) {
        return (
            <div className="p-8 text-center border rounded-md">
                <div className="text-muted">No {isSecondary ? 'secondary' : 'primary'} metrics configured</div>
            </div>
        )
    }

    return (
        <div className="w-full overflow-x-auto rounded-md border">
            <table className="w-full border-collapse text-sm">
                <colgroup>
                    <col className="min-w-[200px]" />
                    <col />
                    <col />
                    <col />
                    <col />
                    <col className="min-w-[400px]" />
                </colgroup>
                <TableHeader axisRange={axisRange} />
                <tbody>
                    {metrics.map((metric, metricIndex) => {
                        const result = results[metricIndex]
                        const error = errors[metricIndex]

                        const isLoading = !result && !error && !!experiment.start_date

                        return (
                            <MetricRowGroup
                                key={metricIndex}
                                metric={metric}
                                result={result}
                                experiment={experiment}
                                metricType={getInsightType(metric)}
                                metricIndex={metricIndex}
                                axisRange={axisRange}
                                isSecondary={isSecondary}
                                isLastMetric={metricIndex === metrics.length - 1}
                                isAlternatingRow={metricIndex % 2 === 1}
                                onDuplicateMetric={() => {
                                    duplicateMetric({ metricIndex, isSecondary })
                                    updateExperimentMetrics()
                                }}
                                error={error}
                                isLoading={isLoading}
                                hasMinimumExposureForResults={hasMinimumExposureForResults}
                                showDetailsModal={showDetailsModal}
                            />
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}
