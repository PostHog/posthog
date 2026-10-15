import { ActionsNode, DataWarehouseNode, EventsNode, GroupNode, NodeKind } from '~/queries/schema/schema-general'

/** Expand GroupNodes into individual EventsNode/ActionsNode for insight types that don't support GroupNode */
export const expandGroupNodes = (
    series: (EventsNode | ActionsNode | DataWarehouseNode | GroupNode)[]
): (EventsNode | ActionsNode | DataWarehouseNode)[] => {
    return series.flatMap((item) =>
        item.kind === NodeKind.GroupNode ? (item.nodes as (EventsNode | ActionsNode | DataWarehouseNode)[]) : [item]
    )
}
