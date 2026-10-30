import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import {
    SeriesNode,
    isActionsSeriesNode,
    isEventsSeriesNode,
    isGroupSeriesNode,
    isWarehouseSeriesNode,
    seriesNodeEntityType,
    toActionId,
} from 'scenes/insights/filters/ActionFilter/seriesNode'

import { NodeKind } from '~/queries/schema/schema-general'
import { EntityTypes } from '~/types'

export interface CdpFilterEntity {
    id?: any
    type?: any
    order?: number
    [key: string]: any
}

/**
 * The matcher rows of a hog function, mapping, workflow or usage metric filter. The bytecode compiler in
 * `posthog/cdp/filters.py` and the Node runtime read these rows as stored, so a round trip through the
 * picker must give back the same JSON.
 */
export interface CdpFilterEntities {
    actions: CdpFilterEntity[]
    events: CdpFilterEntity[]
    data_warehouse: CdpFilterEntity[]
    groups: CdpFilterEntity[]
}

const ENTITY_IDENTITY_KEYS = ['type', 'id', 'order', 'index', 'nestedFilters', 'uuid']
const NODE_IDENTITY_KEYS = ['kind', 'version', 'event', 'id', 'nodes']

function omitKeys(source: Record<string, any>, keys: string[]): Record<string, any> {
    return Object.fromEntries(Object.entries(source).filter(([key]) => !keys.includes(key)))
}

// The picker replaces its rows with every new series array it receives. A parent can render again before it
// receives the filters that hold a new row, so the same filters object must give back the same array.
const seriesByFilters = new WeakMap<Partial<CdpFilterEntities>, SeriesNode[]>()

export function cdpFiltersToSeries(filters: Partial<CdpFilterEntities> | null | undefined): SeriesNode[] {
    if (!filters) {
        return []
    }
    let series = seriesByFilters.get(filters)
    if (!series) {
        series = [
            ...(filters.actions ?? []),
            ...(filters.events ?? []),
            ...(filters.data_warehouse ?? []),
            ...(filters.groups ?? []),
        ]
            .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
            .map(cdpFilterEntityToSeriesNode)
        seriesByFilters.set(filters, series)
    }
    return series
}

function cdpFilterEntityToSeriesNode(entity: CdpFilterEntity): SeriesNode {
    const shared = omitKeys(entity, ENTITY_IDENTITY_KEYS)
    if (Array.isArray(shared.properties)) {
        shared.properties = convertPropertyGroupToProperties(shared.properties)
    }

    if (entity.type === EntityTypes.ACTIONS) {
        return { ...shared, kind: NodeKind.ActionsNode, id: toActionId(entity.id) } as SeriesNode
    }
    if (entity.type === EntityTypes.GROUPS) {
        return {
            ...shared,
            kind: NodeKind.GroupNode,
            nodes: (entity.nestedFilters ?? []).map(cdpFilterEntityToSeriesNode),
        } as SeriesNode
    }
    if (entity.type === EntityTypes.DATA_WAREHOUSE) {
        const tableName = shared.table_name ?? (typeof entity.id === 'string' ? entity.id : undefined)
        return {
            ...shared,
            kind: NodeKind.DataWarehouseNode,
            table_name: tableName,
            id: tableName ?? entity.id,
        } as SeriesNode
    }
    return { ...shared, kind: NodeKind.EventsNode, event: entity.id } as SeriesNode
}

export function seriesToCdpFilters(series: SeriesNode[]): CdpFilterEntities {
    const entities = series.map(seriesNodeToCdpFilterEntity)
    return {
        actions: entities.filter((entity) => entity.type === EntityTypes.ACTIONS),
        events: entities.filter((entity) => entity.type === EntityTypes.EVENTS),
        data_warehouse: entities.filter((entity) => entity.type === EntityTypes.DATA_WAREHOUSE),
        groups: entities.filter((entity) => entity.type === EntityTypes.GROUPS),
    }
}

function seriesNodeToCdpFilterEntity(node: SeriesNode, order: number): CdpFilterEntity {
    let id: string | number | null = null
    if (isEventsSeriesNode(node)) {
        id = node.event ?? null
    } else if (isActionsSeriesNode(node)) {
        id = node.id
    } else if (isWarehouseSeriesNode(node)) {
        id = node.table_name
    }

    return {
        ...omitKeys(node, NODE_IDENTITY_KEYS),
        ...(isGroupSeriesNode(node)
            ? {
                  nestedFilters: node.nodes.map((nested, nestedOrder) =>
                      seriesNodeToCdpFilterEntity(nested, nestedOrder)
                  ),
              }
            : {}),
        id,
        type: seriesNodeEntityType(node) ?? EntityTypes.EVENTS,
        order,
    }
}
