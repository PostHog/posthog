import type { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'

export const getMetricTag = (metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery): string => {
    if (metric.kind === NodeKind.ExperimentMetric) {
        return metric.metric_type.charAt(0).toUpperCase() + metric.metric_type.slice(1).toLowerCase()
    } else if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        return 'Funnel'
    }
    return 'Trend'
}

export const getDefaultMetricTitle = (metric: ExperimentMetric): string => {
    if (metric.metric_config.kind === NodeKind.ExperimentEventMetricConfig) {
        return metric.metric_config.event
    } else if (metric.metric_config.kind === NodeKind.ExperimentActionMetricConfig) {
        return metric.metric_config.name || `Action ${metric.metric_config.action}`
    }
    return 'Untitled metric'
}
