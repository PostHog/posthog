import { ExperimentFunnelsQuery } from '~/queries/schema/schema-general'
import { ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetric } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { MetricHeader } from '../shared/MetricHeader'
import { getNiceTickValues } from '../shared/utils'
import { BAR_HEIGHT, BAR_SPACING, VIEW_BOX_WIDTH } from './constants'
import { VariantBar } from './VariantBar'

export function MetricRow({
    metric,
    metricType,
    result,
    isSecondary,
    metrics,
    metricIndex,
}: {
    metrics: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    metricIndex: number
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    result: any
    metricType: InsightType
    isSecondary: boolean
}): JSX.Element {
    const variants = result?.variant_results || []
    const maxAbsValue = Math.max(
        ...variants.flatMap((variant: any) => {
            const interval = variant.confidence_interval
            return interval ? [Math.abs(interval[0]), Math.abs(interval[1])] : [] // Remove /100
        })
    )

    const axisMargin = Math.max(maxAbsValue * 0.05, 0.1)
    const chartRadius = maxAbsValue + axisMargin
    const tickValues = getNiceTickValues(chartRadius)

    const chartHeight = BAR_SPACING + (BAR_HEIGHT + BAR_SPACING) * variants.length

    const { chartSvgRef, chartSvgHeight } = useSvgResizeObserver([tickValues, chartRadius])
    const metricTitlePanelHeight = Math.max(chartSvgHeight, 60)

    return (
        <div
            className={`w-full border border-primary bg-light ${metricIndex === metrics.length - 1 ? 'rounded-b' : ''}`}
        >
            <div className="flex">
                <div className="w-1/5 border-r border-primary">
                    <div
                        className="p-2"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${metricTitlePanelHeight}px` }}
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
                    style={{ height: `${chartSvgHeight}px` }}
                >
                    <div className="relative w-full max-w-screen">
                        <div className="flex justify-center">
                            <svg
                                ref={chartSvgRef}
                                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`}
                                preserveAspectRatio="xMidYMid meet"
                                className="ml-12 max-w-[1000px]"
                            >
                                {/* Variant bars */}
                                {variants.map((variant: any, index: number) => (
                                    <VariantBar
                                        key={variant.key}
                                        variant={variant}
                                        index={index}
                                        chartRadius={chartRadius}
                                        metricIndex={metricIndex}
                                        isSecondary={isSecondary}
                                    />
                                ))}
                            </svg>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
