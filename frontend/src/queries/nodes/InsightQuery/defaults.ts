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
import { BaseMathType, FunnelVizType, PathType, RetentionPeriod } from '~/types'
import { ShownAsValue } from 'lib/constants'

const trendsQueryDefault: TrendsQuery = {
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

const funnelsQueryDefault: FunnelsQuery = {
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
    lifecycleFilter: { shown_as: ShownAsValue.LIFECYCLE },
}

export const nodeKindToDefaultQuery: Record<InsightNodeKind, InsightQueryNode> = {
    [NodeKind.TrendsQuery]: trendsQueryDefault,
    [NodeKind.FunnelsQuery]: funnelsQueryDefault,
    [NodeKind.RetentionQuery]: retentionQueryDefault,
    [NodeKind.PathsQuery]: pathsQueryDefault,
    [NodeKind.StickinessQuery]: stickinessQueryDefault,
    [NodeKind.LifecycleQuery]: lifecycleQueryDefault,
}
