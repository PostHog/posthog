import type { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'

export const getMetricTag = (metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery): string => {
    if (metric.kind === NodeKind.ExperimentMetric) {
        return metric.metric_type.charAt(0).toUpperCase() + metric.metric_type.slice(1).toLowerCase()
    } else if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        return 'Funnel'
    }
    return 'Trend'
}

export const getDefaultMetricTitle = (metric: ExperimentMetric): string => {
    switch (metric.metric_type) {
        case ExperimentMetricType.MEAN:
            if (metric.source.type === 'event') {
                return metric.source.event
            } else if (metric.source.type === 'action') {
                return metric.source.name || `Action ${metric.source.action}`
            }
            return 'Untitled metric'
        case ExperimentMetricType.FUNNEL:
            return metric.steps[0].event
    }
}
