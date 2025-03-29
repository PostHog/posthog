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

export const getDefaultMetricTitle = (metric: ExperimentMetric): string => {
    const getDefaultName = (
        entity: EventsNode | ActionsNode | ExperimentDataWarehouseNode
    ): string | null | undefined => {
        if (entity.kind === NodeKind.EventsNode) {
            return entity.name || entity.event
        } else if (entity.kind === NodeKind.ActionsNode) {
            return entity.name || `Action ${entity.id}`
        } else if (entity.kind === NodeKind.ExperimentDataWarehouseNode) {
            return entity.table_name
        }
    }

    switch (metric.metric_type) {
        case ExperimentMetricType.MEAN:
            return getDefaultName(metric.source) || 'Untitled metric'
        case ExperimentMetricType.FUNNEL:
            return getDefaultName(metric.series[0]) || 'Untitled funnel'
    }
}
