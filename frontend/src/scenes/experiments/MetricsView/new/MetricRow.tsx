import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { EXPERIMENT_MAX_PRIMARY_METRICS, EXPERIMENT_MAX_SECONDARY_METRICS } from 'scenes/experiments/constants'
import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { ChartEmptyState } from '../shared/ChartEmptyState'
import { ChartLoadingState } from '../shared/ChartLoadingState'
import { MetricHeader } from '../shared/MetricHeader'
import { getNiceTickValues } from '../shared/utils'
import { Chart } from './Chart'
import { DetailsButton } from './DetailsButton'
import { DetailsModal } from './DetailsModal'

export function MetricRow({
    metric,
    metricType,
    result,
    isSecondary,
    metrics,
    metricIndex,
    chartRadius,
    error,
}: {
    metrics: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    metricIndex: number
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    result: any
    metricType: InsightType
    isSecondary: boolean
    chartRadius: number
    error: any
}): JSX.Element {
    const {
        experiment,
        secondaryMetricsResultsLoading,
        primaryMetricsResultsLoading,
        hasMinimumExposureForResults,
        primaryMetricsLengthWithSharedMetrics,
        secondaryMetricsLengthWithSharedMetrics,
    } = useValues(experimentLogic)
    const { duplicateMetric, updateExperimentMetrics } = useActions(experimentLogic)
    const resultsLoading = isSecondary ? secondaryMetricsResultsLoading : primaryMetricsResultsLoading

    // Check if duplicating would exceed the metric limit
    const currentMetricCount = isSecondary
        ? secondaryMetricsLengthWithSharedMetrics
        : primaryMetricsLengthWithSharedMetrics
    const canDuplicateMetric =
        currentMetricCount < (isSecondary ? EXPERIMENT_MAX_SECONDARY_METRICS : EXPERIMENT_MAX_PRIMARY_METRICS)

    const variantResults = result?.variant_results || []

    const tickValues = getNiceTickValues(chartRadius)

    const { chartSvgRef, chartSvgHeight } = useSvgResizeObserver([tickValues, chartRadius])
    const panelHeight = Math.max(chartSvgHeight, 60)

    const [isModalOpen, setIsModalOpen] = useState(false)

    return (
        <div
            className={`w-full border border-primary bg-light ${metricIndex === metrics.length - 1 ? 'rounded-b' : ''}`}
        >
            <div className="flex">
                <div className="w-1/5 border-r border-primary">
                    <div
                        className="p-2"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${panelHeight}px` }}
                    >
                        <MetricHeader
                            metricIndex={metricIndex}
                            metric={metric}
                            metricType={metricType}
                            isPrimaryMetric={!isSecondary}
                            canDuplicateMetric={canDuplicateMetric}
                            onDuplicateMetricClick={() => {
                                duplicateMetric({ metricIndex, isSecondary })
                                updateExperimentMetrics()
                            }}
                        />
                    </div>
                </div>
                <div
                    className="w-4/5 min-w-[780px]"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: `${panelHeight}px` }}
                >
                    {resultsLoading ? (
                        <ChartLoadingState height={panelHeight} />
                    ) : result && hasMinimumExposureForResults ? (
                        <div className="relative">
                            <Chart
                                chartSvgRef={chartSvgRef}
                                variantResults={variantResults}
                                chartRadius={chartRadius}
                                metricIndex={metricIndex}
                                tickValues={tickValues}
                                isSecondary={isSecondary}
                            />
                            <DetailsButton
                                metric={metric}
                                isSecondary={isSecondary}
                                experiment={experiment}
                                setIsModalOpen={setIsModalOpen}
                            />
                            <DetailsModal
                                isOpen={isModalOpen}
                                onClose={() => setIsModalOpen(false)}
                                metric={metric}
                                result={result}
                                experiment={experiment}
                                metricIndex={metricIndex}
                                isSecondary={isSecondary}
                            />
                        </div>
                    ) : (
                        <ChartEmptyState
                            height={panelHeight}
                            experimentStarted={!!experiment.start_date}
                            hasMinimumExposure={hasMinimumExposureForResults}
                            metric={metric}
                            error={error}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
