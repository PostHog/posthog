import { IconArrowRight, IconFunnels } from '@posthog/icons'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { getDefaultMetricTitle } from './utils'

export const MetricTitle = ({ metric, metricType }: { metric: any; metricType?: InsightType }): JSX.Element => {
    if (metric.name) {
        return <span className="truncate">{metric.name}</span>
    }

    if (metric.kind === NodeKind.ExperimentMetric) {
        return <span className="truncate">{getDefaultMetricTitle(metric)}</span>
    }

    if (metricType === InsightType.TRENDS && metric.count_query?.series?.[0]?.name) {
        return <span className="truncate">{metric.count_query.series[0].name}</span>
    }

    if (metricType === InsightType.FUNNELS && metric.funnels_query?.series) {
        const series = metric.funnels_query.series
        if (series.length > 0) {
            const firstStep = series[0]?.name
            const lastStep = series[series.length - 1]?.name

            return (
                <div className="inline-flex flex-wrap items-center gap-1 min-w-0">
                    <div className="inline-flex items-center gap-1 min-w-0">
                        <IconFunnels className="text-secondary flex-shrink-0" fontSize="14" />
                        <span className="truncate">{firstStep}</span>
                    </div>
                    <div className="inline-flex items-center gap-1 min-w-0 @max-[200px]:ml-5">
                        <IconArrowRight className="text-secondary flex-shrink-0" fontSize="14" />
                        <span className="truncate">{lastStep}</span>
                    </div>
                </div>
            )
        }
    }

    return <span className="text-secondary truncate">Untitled metric</span>
}
