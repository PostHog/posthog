import { useActions, useValues } from 'kea'

import { InsightType } from '~/types'

import { experimentLogic } from '../../experimentLogic'
import { insertMetricIntoOrderingArray } from '../../utils'
import { MetricResult } from '../shared/metricsState'
import { type ExperimentVariantResult, getVariantInterval } from '../shared/utils'
import { MetricRowGroup } from './MetricRowGroup'
import { TableHeader } from './TableHeader'

interface MetricsTableProps {
    metrics: MetricResult[]
    isSecondary: boolean
    showDetailsModal?: boolean
}

export function MetricsTable({ metrics, isSecondary, showDetailsModal = true }: MetricsTableProps): JSX.Element {
    const { experiment, hasMinimumExposureForResults, getInsightType } = useValues(experimentLogic)
    const { duplicateMetric, updateExperimentMetrics, setExperiment } = useActions(experimentLogic)

    // Calculate shared axisRange across all metrics
    const maxAbsValue = Math.max(
        ...metrics.flatMap((metricResult: MetricResult) => {
            const variantResults = metricResult.result?.variant_results || []
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
                    {metrics.map((metricResult, index) => {
                        return (
                            <MetricRowGroup
                                key={metricResult.uuid}
                                metric={metricResult.definition}
                                result={metricResult.result}
                                experiment={experiment}
                                metricType={getInsightType(metricResult.definition) as InsightType}
                                displayOrder={index}
                                axisRange={axisRange}
                                isSecondary={isSecondary}
                                isLastMetric={index === metrics.length - 1}
                                isAlternatingRow={index % 2 === 1}
                                onDuplicateMetric={() => {
                                    const uuid = metricResult.uuid
                                    if (!uuid || !experiment) {
                                        return
                                    }

                                    const newUuid = crypto.randomUUID()

                                    duplicateMetric({ uuid, isSecondary, newUuid })

                                    const newOrderingArray = insertMetricIntoOrderingArray(
                                        experiment,
                                        newUuid,
                                        uuid,
                                        isSecondary
                                    )
                                    setExperiment({
                                        [isSecondary
                                            ? 'secondary_metrics_ordered_uuids'
                                            : 'primary_metrics_ordered_uuids']: newOrderingArray,
                                    })

                                    updateExperimentMetrics()
                                }}
                                error={metricResult.error}
                                isLoading={metricResult.isLoading}
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
