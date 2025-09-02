import {
    FunnelsQuery,
    InsightNodeKind,
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

export const trendsQueryDefault: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            name: '$pageview',
            event: '$pageview',
            math: BaseMathType.TotalCount,
        },
    ],
    trendsFilter: {},
}

export const calendarHeatmapQueryDefault: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            name: '$pageview',
            event: '$pageview',
            math: BaseMathType.TotalCount,
        },
    ],
    trendsFilter: {
        display: ChartDisplayType.CalendarHeatmap,
    },
}

export const funnelsQueryDefault: FunnelsQuery = {
    kind: NodeKind.FunnelsQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            name: '$pageview',
            event: '$pageview',
        },
    ],
    funnelsFilter: {
        funnelVizType: FunnelVizType.Steps,
    },
}

const retentionQueryDefault: RetentionQuery = {
    kind: NodeKind.RetentionQuery,
    retentionFilter: {
        period: RetentionPeriod.Day,
        totalIntervals: 8,
        targetEntity: {
            id: '$pageview',
            name: '$pageview',
            type: 'events',
        },
        returningEntity: {
            id: '$pageview',
            name: '$pageview',
            type: 'events',
        },
        retentionType: 'retention_first_time',
        meanRetentionCalculation: 'simple',
    },
}

const pathsQueryDefault: PathsQuery = {
    kind: NodeKind.PathsQuery,
    pathsFilter: {
        includeEventTypes: [PathType.PageView],
    },
}

const stickinessQueryDefault: StickinessQuery = {
    kind: NodeKind.StickinessQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            name: '$pageview',
            event: '$pageview',
            math: BaseMathType.UniqueUsers,
        },
    ],
    stickinessFilter: {
        computedAs: StickinessComputationModes.NonCumulative,
    },
}

const lifecycleQueryDefault: LifecycleQuery = {
    kind: NodeKind.LifecycleQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            name: '$pageview',
            event: '$pageview',
        },
    ],
}

export const nodeKindToDefaultQuery: Record<InsightNodeKind, InsightQueryNode> = {
    [NodeKind.TrendsQuery]: trendsQueryDefault,
    [NodeKind.FunnelsQuery]: funnelsQueryDefault,
    [NodeKind.RetentionQuery]: retentionQueryDefault,
    [NodeKind.PathsQuery]: pathsQueryDefault,
    [NodeKind.StickinessQuery]: stickinessQueryDefault,
    [NodeKind.LifecycleQuery]: lifecycleQueryDefault,
}
