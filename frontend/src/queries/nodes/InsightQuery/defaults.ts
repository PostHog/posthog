import { getDefaultEventName } from 'lib/utils/getAppContext'

import {
    FunnelsQuery,
    InsightQueryNode,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    RetentionQuery,
    StickinessComputationModes,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, FunnelVizType, PathType, RetentionPeriod } from '~/types'

function getTrendsQueryDefault(): TrendsQuery {
    const defaultEvent = getDefaultEventName()
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultEvent === null ? 'All events' : defaultEvent,
                event: defaultEvent,
                math: BaseMathType.TotalCount,
            },
        ],
        trendsFilter: {},
    }
}

function getCalendarHeatmapQueryDefault(): TrendsQuery {
    const defaultEvent = getDefaultEventName()
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultEvent === null ? 'All events' : defaultEvent,
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
    return {
        kind: NodeKind.FunnelsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultEvent === null ? 'All events' : defaultEvent,
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
    const eventName = defaultEvent === null ? 'All events' : defaultEvent
    return {
        kind: NodeKind.RetentionQuery,
        retentionFilter: {
            period: RetentionPeriod.Day,
            totalIntervals: 8,
            targetEntity: {
                id: defaultEvent ?? undefined,
                name: eventName,
                type: 'events',
            },
            returningEntity: {
                id: defaultEvent ?? undefined,
                name: eventName,
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
        pathsFilter: {
            includeEventTypes: [pathType],
        },
    }
}

function getStickinessQueryDefault(): StickinessQuery {
    const defaultEvent = getDefaultEventName()
    return {
        kind: NodeKind.StickinessQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultEvent === null ? 'All events' : defaultEvent,
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
    return {
        kind: NodeKind.LifecycleQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: defaultEvent === null ? 'All events' : defaultEvent,
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
