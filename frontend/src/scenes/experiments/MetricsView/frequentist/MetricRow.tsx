import { ExperimentFunnelsQuery } from '~/queries/schema/schema-general'
import { ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetric } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { MetricHeader } from '../MetricHeader'

export function MetricRow({
    metric,
    metricType,
    isSecondary,
    metrics,
    metricIndex,
}: {
    metrics: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
    metricIndex: number
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    metricType: InsightType
    isSecondary: boolean
}): JSX.Element {
    const tickValues = [-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3]
    const chartBound = 0.30445147785257376
    const { chartSvgHeight } = useSvgResizeObserver([tickValues, chartBound])

    const metricTitlePanelHeight = Math.max(chartSvgHeight, 80)

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
                <div className="w-4/5 min-w-[780px]">
                    <div className="flex justify-center">Chart</div>
                </div>
            </div>
        </div>
    )
}
