import { EventsNode, NodeKind } from '~/queries/schema/schema-general'

import { SeriesNode } from '../seriesNode'

export function makeSeriesNode(overrides: Partial<SeriesNode> = {}): SeriesNode {
    return {
        kind: NodeKind.EventsNode,
        event: '$autocapture',
        name: '$autocapture',
        properties: [],
        ...overrides,
    } as EventsNode
}
