import { getDefaultEventLabel, getDefaultEventName } from 'lib/utils/getAppContext'

import {
    FunnelsQuery,
    InsightQueryNode,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    ProductKey,
    RetentionQuery,
    StickinessComputationModes,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, FunnelVizType, PathType, RetentionPeriod } from '~/types'

function getTrendsQueryDefault(): TrendsQuery {
    const defaultEvent = getDefaultEventName()
    const defaultLabel = getDefaultEventLabel()
    return {
        kind: NodeKind.TrendsQuery,
        tags: { productKey: ProductKey.PRODUCT_ANALYTICS },
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultLabel,
                event: defaultEvent,
                math: BaseMathType.TotalCount,
            },
        ],
        trendsFilter: {},
    }
}

function getCalendarHeatmapQueryDefault(): TrendsQuery {
    const defaultEvent = getDefaultEventName()
    const defaultLabel = getDefaultEventLabel()
    return {
        kind: NodeKind.TrendsQuery,
        tags: { productKey: ProductKey.PRODUCT_ANALYTICS },
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultLabel,
                event: defaultEvent,
                math: BaseMathType.TotalCount,
            },
        ],
        trendsFilter: {
            display: ChartDisplayType.CalendarHeatmap,
        },
    }
}

function getFunnelsQueryDefault(): FunnelsQuery {
    const defaultEvent = getDefaultEventName()
    const defaultLabel = getDefaultEventLabel()
    return {
        kind: NodeKind.FunnelsQuery,
        tags: { productKey: ProductKey.PRODUCT_ANALYTICS },
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultLabel,
                event: defaultEvent,
            },
        ],
        funnelsFilter: {
            funnelVizType: FunnelVizType.Steps,
        },
    }
}

function getRetentionQueryDefault(): RetentionQuery {
    const defaultEvent = getDefaultEventName()
    const defaultLabel = getDefaultEventLabel()
    return {
        kind: NodeKind.RetentionQuery,
        tags: { productKey: ProductKey.PRODUCT_ANALYTICS },
        retentionFilter: {
            period: RetentionPeriod.Day,
            totalIntervals: 8,
            targetEntity: {
                id: defaultEvent ?? undefined,
                name: defaultLabel,
                type: 'events',
            },
            returningEntity: {
                id: defaultEvent ?? undefined,
                name: defaultLabel,
                type: 'events',
            },
            retentionType: 'retention_first_time',
            meanRetentionCalculation: 'simple',
        },
    }
}

function getPathsQueryDefault(): PathsQuery {
    const defaultEvent = getDefaultEventName()
    let pathType: PathType
    if (defaultEvent === '$screen') {
        pathType = PathType.Screen
    } else if (defaultEvent === null) {
        pathType = PathType.CustomEvent
    } else {
        pathType = PathType.PageView
    }
    return {
        kind: NodeKind.PathsQuery,
        tags: { productKey: ProductKey.PRODUCT_ANALYTICS },
        pathsFilter: {
            includeEventTypes: [pathType],
            pathReplacements: true,
            showFullUrls: true,
        },
    }
}

function getStickinessQueryDefault(): StickinessQuery {
    const defaultEvent = getDefaultEventName()
    const defaultLabel = getDefaultEventLabel()
    return {
        kind: NodeKind.StickinessQuery,
        tags: { productKey: ProductKey.PRODUCT_ANALYTICS },
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultLabel,
                event: defaultEvent,
                math: BaseMathType.UniqueUsers,
            },
        ],
        stickinessFilter: {
            computedAs: StickinessComputationModes.NonCumulative,
        },
    }
}

function getLifecycleQueryDefault(): LifecycleQuery {
    const defaultEvent = getDefaultEventName()
    const defaultLabel = getDefaultEventLabel()
    return {
        kind: NodeKind.LifecycleQuery,
        tags: { productKey: ProductKey.PRODUCT_ANALYTICS },
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultLabel,
                event: defaultEvent,
            },
        ],
    }
}

/** Product Analytics insight node kinds that support tab switching in the insight UI */
export type ProductAnalyticsInsightNodeKind = Exclude<
    InsightQueryNode['kind'],
    NodeKind.WebStatsTableQuery | NodeKind.WebOverviewQuery
>

/** Legacy exports for backwards compatibility - use getNodeKindToDefaultQuery() instead */
export const trendsQueryDefault = getTrendsQueryDefault()
export const calendarHeatmapQueryDefault = getCalendarHeatmapQueryDefault()
export const funnelsQueryDefault = getFunnelsQueryDefault()

export function getNodeKindToDefaultQuery(): Record<ProductAnalyticsInsightNodeKind, InsightQueryNode> {
    return {
        [NodeKind.TrendsQuery]: getTrendsQueryDefault(),
        [NodeKind.FunnelsQuery]: getFunnelsQueryDefault(),
        [NodeKind.RetentionQuery]: getRetentionQueryDefault(),
        [NodeKind.PathsQuery]: getPathsQueryDefault(),
        [NodeKind.StickinessQuery]: getStickinessQueryDefault(),
        [NodeKind.LifecycleQuery]: getLifecycleQueryDefault(),
    }
}

/** @deprecated Use getNodeKindToDefaultQuery() instead */
export const nodeKindToDefaultQuery = getNodeKindToDefaultQuery()
