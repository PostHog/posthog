import type {
    ActionsNode,
    EventsNode,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
} from '~/queries/schema/schema-general'
import { ExperimentDataWarehouseNode, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'

export const getMetricTag = (metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery): string => {
    if (metric.kind === NodeKind.ExperimentMetric) {
        return metric.metric_type.charAt(0).toUpperCase() + metric.metric_type.slice(1).toLowerCase()
    } else if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        return 'Funnel'
    }
    return 'Trend'
}

type MetricSource = EventsNode | ActionsNode | ExperimentDataWarehouseNode

const getDefaultName = (source: MetricSource): string | null | undefined => {
    switch (source.kind) {
        case NodeKind.EventsNode:
            return source.name || source.event
        case NodeKind.ActionsNode:
            return source.name || `Action ${source.id}`
        case NodeKind.ExperimentDataWarehouseNode:
            return source.table_name
    }
}

export const getDefaultMetricTitle = (metric: ExperimentMetric): string => {
    switch (metric.metric_type) {
        case ExperimentMetricType.MEAN:
            return getDefaultName(metric.source) || 'Untitled metric'
        case ExperimentMetricType.FUNNEL:
            return getDefaultName(metric.series[0]) || 'Untitled funnel'
    }
}
