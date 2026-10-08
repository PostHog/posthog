import { getDefaultEventLabel, getDefaultEventName } from 'lib/utils/getAppContext'

import {
    ActionsNode,
    AnyDataWarehouseNode,
    AnyEntityNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    GroupNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { EntityType, EntityTypes } from '~/types'

/**
 * A row in the series editor. The warehouse arm widens to `ExperimentDataWarehouseNode`,
 * which experiments pass in as their `dataWarehouseNodeKind` and which the schema does not
 * count as an `AnyEntityNode`.
 */
export type SeriesNode = AnyEntityNode<AnyDataWarehouseNode | ExperimentDataWarehouseNode> | GroupNode

/** The node kind the editor creates when a person picks a warehouse table. */
export type WarehouseSeriesNodeKind =
    | NodeKind.DataWarehouseNode
    | NodeKind.FunnelsDataWarehouseNode
    | NodeKind.LifecycleDataWarehouseNode
    | NodeKind.ExperimentDataWarehouseNode

const WAREHOUSE_SERIES_NODE_KINDS = new Set<string>([
    NodeKind.DataWarehouseNode,
    NodeKind.FunnelsDataWarehouseNode,
    NodeKind.LifecycleDataWarehouseNode,
    NodeKind.ExperimentDataWarehouseNode,
])

export function isWarehouseSeriesNodeKind(kind: SeriesNode['kind']): kind is WarehouseSeriesNodeKind {
    return WAREHOUSE_SERIES_NODE_KINDS.has(kind)
}

export function isWarehouseSeriesNode(
    node: SeriesNode | null | undefined
): node is AnyDataWarehouseNode | ExperimentDataWarehouseNode {
    return !!node && WAREHOUSE_SERIES_NODE_KINDS.has(node.kind)
}

export function isEventsSeriesNode(node: SeriesNode | null | undefined): node is EventsNode {
    return node?.kind === NodeKind.EventsNode
}

export function isActionsSeriesNode(node: SeriesNode | null | undefined): node is ActionsNode {
    return node?.kind === NodeKind.ActionsNode
}

export function isGroupSeriesNode(node: SeriesNode | null | undefined): node is GroupNode {
    return node?.kind === NodeKind.GroupNode
}

/**
 * An events node with no event queries every event. `getDisplayNameFromEntityNode` reads the
 * same spelling, so both stay on an explicit `null` rather than treating a missing event as
 * all-events.
 */
export function isAllEventsSeriesNode(node: SeriesNode | null | undefined): boolean {
    return isEventsSeriesNode(node) && node.event === null && (!node.name || node.name === 'All events')
}

/**
 * The key the row queries: the event, the action id, or the table. A group has none of its
 * own, so it reports `null` and the editor identifies it by index alone.
 */
export function seriesNodeKey(node: SeriesNode | null | undefined): string | number | null {
    if (!node) {
        return null
    }
    if (isEventsSeriesNode(node)) {
        return node.event ?? null
    }
    if (isActionsSeriesNode(node)) {
        return node.id
    }
    if (isWarehouseSeriesNode(node)) {
        return node.table_name
    }
    return null
}

const ENTITY_TYPE_BY_SERIES_NODE_KIND: Partial<Record<string, EntityType>> = {
    [NodeKind.EventsNode]: EntityTypes.EVENTS,
    [NodeKind.ActionsNode]: EntityTypes.ACTIONS,
    [NodeKind.DataWarehouseNode]: EntityTypes.DATA_WAREHOUSE,
    [NodeKind.FunnelsDataWarehouseNode]: EntityTypes.DATA_WAREHOUSE,
    [NodeKind.LifecycleDataWarehouseNode]: EntityTypes.DATA_WAREHOUSE,
    [NodeKind.ExperimentDataWarehouseNode]: EntityTypes.DATA_WAREHOUSE,
    [NodeKind.GroupNode]: EntityTypes.GROUPS,
}

/** For the parts of the UI still keyed by the legacy entity type. */
export function seriesNodeEntityType(node: SeriesNode | null | undefined): EntityType | undefined {
    return node ? ENTITY_TYPE_BY_SERIES_NODE_KIND[node.kind] : undefined
}

export function seriesNodeKindForEntityType(
    type: EntityType | null | undefined,
    warehouseKind: WarehouseSeriesNodeKind
): SeriesNode['kind'] {
    switch (type) {
        case EntityTypes.ACTIONS:
            return NodeKind.ActionsNode
        case EntityTypes.DATA_WAREHOUSE:
            return warehouseKind
        case EntityTypes.GROUPS:
            return NodeKind.GroupNode
        default:
            return NodeKind.EventsNode
    }
}

/**
 * An action id reaches the editor as a string from the taxonomic picker, while the schema types
 * `ActionsNode.id` as an integer. Coerce once, here, so no consumer has to repair it later.
 */
export function toActionId(id: string | number | null | undefined): number {
    return typeof id === 'string' ? parseInt(id) : (id ?? 0)
}

export function withLatestVersion<T extends SeriesNode>(node: T): T {
    return setLatestVersionsOnQuery(node)
}

export function createDefaultEventsNode(defaults?: Partial<EventsNode>): EventsNode {
    return withLatestVersion({
        kind: NodeKind.EventsNode,
        event: getDefaultEventName(),
        name: getDefaultEventLabel(),
        ...defaults,
    } as EventsNode)
}
