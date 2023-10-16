import {
    FunnelsQuery,
    InsightNodeKind,
    InsightQueryNode,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema'
import { BaseMathType, FunnelVizType, InsightType, PathType, RetentionPeriod } from '~/types'

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
        funnel_viz_type: FunnelVizType.Steps,
    },
}

const retentionQueryDefault: RetentionQuery = {
    kind: NodeKind.RetentionQuery,
    retentionFilter: {
        period: RetentionPeriod.Day,
        total_intervals: 11,
        target_entity: {
            id: '$pageview',
            name: '$pageview',
            type: 'events',
        },
        returning_entity: {
            id: '$pageview',
            name: '$pageview',
            type: 'events',
        },
        retention_type: 'retention_first_time',
    },
}

const pathsQueryDefault: PathsQuery = {
    kind: NodeKind.PathsQuery,
    pathsFilter: {
        include_event_types: [PathType.PageView],
    },
}

const stickinessQueryDefault: StickinessQuery = {
    kind: NodeKind.StickinessQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            name: '$pageview',
            event: '$pageview',
            math: BaseMathType.TotalCount,
        },
    ],
    stickinessFilter: {},
}

const lifecycleQueryDefault: LifecycleQuery = {
    kind: NodeKind.LifecycleQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            name: '$pageview',
            event: '$pageview',
            math: BaseMathType.TotalCount,
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

export const insightTypeToDefaultQuery: Record<
    Exclude<InsightType, InsightType.SQL | InsightType.JSON>,
    InsightQueryNode
> = {
    [InsightType.TRENDS]: trendsQueryDefault,
    [InsightType.FUNNELS]: funnelsQueryDefault,
    [InsightType.RETENTION]: retentionQueryDefault,
    [InsightType.PATHS]: pathsQueryDefault,
    [InsightType.STICKINESS]: stickinessQueryDefault,
    [InsightType.LIFECYCLE]: lifecycleQueryDefault,
}
