import { useValues } from 'kea'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { ExperimentFunnelsQuery } from '~/queries/schema/schema-general'
import { ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetric } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { ChartLoadingState } from '../shared/ChartLoadingState'
import { MetricHeader } from '../shared/MetricHeader'
import { getNiceTickValues } from '../shared/utils'
import { Chart } from './Chart'
import { BAR_HEIGHT, BAR_SPACING } from './constants'

export function MetricRow({
    metric,
    metricType,
    result,
    isSecondary,
    metrics,
    metricIndex,
    chartRadius,
}: {
    metrics: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    metricIndex: number
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    result: any
    metricType: InsightType
    isSecondary: boolean
    chartRadius: number
}): JSX.Element {
    const { secondaryMetricResultsLoading, metricResultsLoading } = useValues(experimentLogic)
    const resultsLoading = isSecondary ? secondaryMetricResultsLoading : metricResultsLoading

    const variantResults = result?.variant_results || []

    const tickValues = getNiceTickValues(chartRadius)
    const chartHeight = BAR_SPACING + (BAR_HEIGHT + BAR_SPACING) * variantResults.length

    const { chartSvgRef, chartSvgHeight } = useSvgResizeObserver([tickValues, chartRadius])
    const panelHeight = Math.max(chartSvgHeight, 60)

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
                            onDuplicateMetricClick={() => {
                                // grab from utils
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
                    ) : (
                        <Chart
                            chartSvgRef={chartSvgRef}
                            chartHeight={chartHeight}
                            variantResults={variantResults}
                            chartRadius={chartRadius}
                            metricIndex={metricIndex}
                            tickValues={tickValues}
                            isSecondary={isSecondary}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
