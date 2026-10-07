import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { uuid } from 'lib/utils/dom'

import { AnyEntityNode, GroupNode, NodeKind } from '~/queries/schema/schema-general'
import { ActionFilter, Entity, EntityTypes, FilterType } from '~/types'

import {
    SeriesNode,
    WarehouseSeriesNodeKind,
    isActionsSeriesNode,
    isEventsSeriesNode,
    isGroupSeriesNode,
    isWarehouseSeriesNode,
    seriesNodeEntityType,
    seriesNodeKindForEntityType,
    toActionId,
} from './seriesNode'

/**
 * Translation between the series editor's query nodes and the legacy entity filter shape that
 * CDP, workflows, heatmaps, usage metrics, dashboard templates and retention still persist.
 *
 * Only four things translate: `type` to `kind`, `id` to the node's own key, `order` to the array
 * index, and `nestedFilters` to `nodes`. Everything else, including warehouse popover fields a
 * caller declares itself, keeps its name and is copied through untouched.
 */

/** Keys that mean something different on each side, so neither side copies them blindly. */
const TRANSLATED_LEGACY_KEYS = ['type', 'id', 'order', 'index', 'nestedFilters', 'uuid'] as const
const TRANSLATED_NODE_KEYS = ['kind', 'version', 'event', 'id', 'nodes'] as const

function omit<T extends Record<string, any>>(source: T, keys: readonly string[]): Record<string, any> {
    const result: Record<string, any> = {}
    for (const [key, value] of Object.entries(source)) {
        if (!keys.includes(key)) {
            result[key] = value
        }
    }
    return result
}

function legacyFilterToSeriesNode(filter: ActionFilter, warehouseKind: WarehouseSeriesNodeKind): SeriesNode {
    const kind = seriesNodeKindForEntityType(filter.type, warehouseKind)
    const shared = omit(filter, TRANSLATED_LEGACY_KEYS)

    // A legacy filter may carry a property group where a node carries a flat list.
    if (Array.isArray(filter.properties)) {
        shared.properties = convertPropertyGroupToProperties(filter.properties)
    }

    if (kind === NodeKind.ActionsNode) {
        return { ...shared, kind, id: toActionId(filter.id) } as SeriesNode
    }
    if (kind === NodeKind.GroupNode) {
        return {
            ...shared,
            kind,
            nodes: (filter.nestedFilters ?? []).map(
                (nested) => legacyFilterToSeriesNode(nested as ActionFilter, warehouseKind) as AnyEntityNode
            ),
        } as GroupNode as SeriesNode
    }
    if (kind !== NodeKind.EventsNode) {
        // Warehouse: `table_name` is the key, and the legacy `id` mirrors it.
        const warehouseTableName = (filter as { table_name?: string }).table_name
        return {
            ...shared,
            kind,
            table_name: warehouseTableName ?? (typeof filter.id === 'string' ? filter.id : undefined),
            id: warehouseTableName ?? filter.id,
        } as SeriesNode
    }
    return { ...shared, kind, event: filter.id } as SeriesNode
}

/** Sorted by the `order` fields, which the editor then carries as the array index. */
export function legacyFiltersToSeries(
    filters: Partial<FilterType> | undefined,
    warehouseKind: WarehouseSeriesNodeKind = NodeKind.DataWarehouseNode
): SeriesNode[] {
    return [
        ...(filters?.[EntityTypes.ACTIONS] || []),
        ...(filters?.[EntityTypes.EVENTS] || []),
        ...(filters?.[EntityTypes.DATA_WAREHOUSE] || []),
        ...(filters?.[EntityTypes.GROUPS] || []),
    ]
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
        .map((filter) => legacyFilterToSeriesNode(filter as ActionFilter, warehouseKind))
}

function seriesNodeToLegacyFilter(node: SeriesNode, order: number): ActionFilter {
    const shared = omit(node, TRANSLATED_NODE_KEYS)
    const type = seriesNodeEntityType(node) ?? EntityTypes.EVENTS

    let id: ActionFilter['id'] = null
    if (isEventsSeriesNode(node)) {
        id = node.event ?? null
    } else if (isActionsSeriesNode(node)) {
        id = node.id
    } else if (isWarehouseSeriesNode(node)) {
        id = node.table_name
    }

    return {
        ...shared,
        ...(isGroupSeriesNode(node)
            ? { nestedFilters: node.nodes.map((nested, nestedOrder) => seriesNodeToLegacyFilter(nested, nestedOrder)) }
            : {}),
        id,
        type,
        order,
    } as ActionFilter
}

/** Reassigns `order` from the array index. */
export function seriesToLegacyFilters(series: SeriesNode[]): FilterType {
    const filters = series.map((node, index) => {
        const filter = seriesNodeToLegacyFilter(node, index)
        // The first step of a funnel cannot be optional.
        return index === 0 ? { ...filter, optionalInFunnel: undefined } : filter
    })

    return {
        [EntityTypes.ACTIONS]: filters.filter((filter) => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: filters.filter((filter) => filter.type === EntityTypes.EVENTS),
        [EntityTypes.DATA_WAREHOUSE]: filters.filter((filter) => filter.type === EntityTypes.DATA_WAREHOUSE),
        [EntityTypes.GROUPS]: filters.filter((filter) => filter.type === EntityTypes.GROUPS),
    } as FilterType
}

/**
 * The legacy row shape, still used by `cleanFilters` for the persons-modal URL path and by
 * replay's playlist summary. Both go in the PR that deletes the converter.
 */
export type LocalFilter = ActionFilter & {
    order: number
    uuid: string
    table_name?: string
    [key: string]: any
}

export type BareEntity = Pick<Entity, 'id' | 'name'>

export function toLocalFilters(filters: Partial<FilterType>): LocalFilter[] {
    const localFilters = [
        ...(filters[EntityTypes.ACTIONS] || []),
        ...(filters[EntityTypes.EVENTS] || []),
        ...(filters[EntityTypes.DATA_WAREHOUSE] || []),
        ...(filters[EntityTypes.GROUPS] || []),
    ]
        .sort((a, b) => a.order - b.order)
        .map((filter, order) => ({ ...(filter as ActionFilter), order }))
    return localFilters.map((filter) =>
        filter.properties && Array.isArray(filter.properties)
            ? {
                  ...filter,
                  uuid: uuid(),
                  properties: convertPropertyGroupToProperties(filter.properties),
              }
            : { ...filter, uuid: uuid() }
    )
}

export function toFilters(localFilters: LocalFilter[]): FilterType {
    const filters = localFilters.map((filter, index) => ({
        ...filter,
        order: index,
        // The first step of a funnel cannot be optional
        optionalInFunnel: index == 0 ? undefined : filter.optionalInFunnel,
    }))

    return {
        [EntityTypes.ACTIONS]: filters.filter((filter) => filter.type === EntityTypes.ACTIONS),
        [EntityTypes.EVENTS]: filters.filter((filter) => filter.type === EntityTypes.EVENTS),
        [EntityTypes.DATA_WAREHOUSE]: filters.filter((filter) => filter.type === EntityTypes.DATA_WAREHOUSE),
        [EntityTypes.GROUPS]: filters.filter((filter) => filter.type === EntityTypes.GROUPS),
    } as FilterType
}
