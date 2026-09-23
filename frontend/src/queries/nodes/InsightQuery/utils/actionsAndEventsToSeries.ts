import { objectCleanWithEmpty } from 'lib/utils/objects'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'

import {
    ActionsNode,
    AnyDataWarehouseNode,
    AnyEntityNode,
    DataWarehouseNode,
    EventsNode,
    FunnelsDataWarehouseNode,
    GroupNode,
    LifecycleDataWarehouseNode,
    MathType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    ActionFilter,
    AnyDataWarehouseFilter,
    BaseMathType,
    CalendarHeatmapMathType,
    EntityTypes,
    FunnelDatawarehouseFilter,
    FunnelMathType,
    GroupMathType,
    HogQLMathType,
    LifecycleDatawarehouseFilter,
    RetentionEntity,
    TrendsDataWarehouseFilter,
    isDataWarehouseFilter,
    isGroupFilter,
} from '~/types'

import { cleanEntityProperties } from './cleanProperties'

export const actorsOnlyMathTypes = [
    BaseMathType.UniqueUsers,
    BaseMathType.WeeklyActiveUsers,
    BaseMathType.MonthlyActiveUsers,
    GroupMathType.UniqueGroup,
    HogQLMathType.HogQL,
]

const funnelsMathTypes = [FunnelMathType.FirstTimeForUser, FunnelMathType.FirstTimeForUserWithFilters]

const calendarHeatmapMathTypes = [CalendarHeatmapMathType.TotalCount, CalendarHeatmapMathType.UniqueUsers]

export type FilterTypeActionsAndEvents = {
    events?: ActionFilter[]
    actions?: ActionFilter[]
    data_warehouse?: AnyDataWarehouseFilter[]
    new_entity?: ActionFilter[]
    groups?: ActionFilter[]
}

type DataWarehouseNodeKind =
    | NodeKind.DataWarehouseNode
    | NodeKind.FunnelsDataWarehouseNode
    | NodeKind.LifecycleDataWarehouseNode

export const legacyEntityToNode = (
    entity: ActionFilter | AnyDataWarehouseFilter,
    includeProperties: boolean,
    mathAvailability: MathAvailability,
    dataWarehouseNodeKind: DataWarehouseNodeKind = NodeKind.DataWarehouseNode
): AnyEntityNode<AnyDataWarehouseNode> | GroupNode<AnyDataWarehouseNode> => {
    let shared: Partial<
        EventsNode | ActionsNode | DataWarehouseNode | FunnelsDataWarehouseNode | LifecycleDataWarehouseNode | GroupNode
    > = {
        name: entity.name || undefined,
        custom_name: entity.custom_name || undefined,
    }

    if (isDataWarehouseFilter(entity)) {
        shared = {
            ...shared,
            timestamp_field: entity.timestamp_field || undefined,
            table_name: entity.table_name || undefined,
            ...(dataWarehouseNodeKind === NodeKind.LifecycleDataWarehouseNode
                ? {
                      aggregation_target_field: (entity as LifecycleDatawarehouseFilter).aggregation_target_field,
                      created_at_field: (entity as LifecycleDatawarehouseFilter).created_at_field,
                  }
                : dataWarehouseNodeKind === NodeKind.FunnelsDataWarehouseNode
                  ? {
                        id_field: (entity as FunnelDatawarehouseFilter).id_field || undefined,
                        aggregation_target_field:
                            (entity as FunnelDatawarehouseFilter).aggregation_target_field || undefined,
                    }
                  : {
                        id_field: (entity as TrendsDataWarehouseFilter).id_field || undefined,
                        distinct_id_field: (entity as TrendsDataWarehouseFilter).distinct_id_field || undefined,
                    }),
        } as DataWarehouseNode | FunnelsDataWarehouseNode | LifecycleDataWarehouseNode
    }

    if (isGroupFilter(entity)) {
        shared = {
            ...shared,
            operator: entity.operator || undefined,
            nodes: (entity.nestedFilters || []).map((v) =>
                legacyEntityToNode(
                    v as ActionFilter | AnyDataWarehouseFilter,
                    includeProperties,
                    mathAvailability,
                    dataWarehouseNodeKind
                )
            ),
        } as GroupNode
    }

    if (includeProperties) {
        shared = { ...shared, properties: cleanEntityProperties(entity.properties) } as any
    }

    if (mathAvailability !== MathAvailability.None) {
        // only trends, funnels, and stickiness insights support math.
        // transition to then default math for stickiness, when an unsupported math type is encountered.
        if (mathAvailability === MathAvailability.ActorsOnly && !actorsOnlyMathTypes.includes(entity.math as any)) {
            shared = {
                ...shared,
                math: BaseMathType.UniqueUsers,
            }
        } else if (mathAvailability === MathAvailability.FunnelsOnly) {
            if (funnelsMathTypes.includes(entity.math as any)) {
                shared = {
                    ...shared,
                    math: entity.math as MathType,
                }
            }
            if (entity.optionalInFunnel) {
                shared = {
                    ...shared,
                    optionalInFunnel: true,
                }
            }
        } else if (mathAvailability === MathAvailability.CalendarHeatmapOnly) {
            if (calendarHeatmapMathTypes.includes(entity.math as any)) {
                shared = {
                    ...shared,
                    math: entity.math as MathType,
                }
            }
        } else {
            shared = {
                ...shared,
                math: entity.math || 'total',
                math_property: entity.math_property,
                math_property_type: entity.math_property_type,
                math_hogql: entity.math_hogql,
                math_group_type_index: entity.math_group_type_index,
            } as any
        }
    }

    if (entity.type === 'actions') {
        return setLatestVersionsOnQuery(
            objectCleanWithEmpty({
                kind: NodeKind.ActionsNode,
                id: entity.id,
                ...shared,
            })
        ) as any
    } else if (entity.type === 'data_warehouse') {
        return setLatestVersionsOnQuery(
            objectCleanWithEmpty({
                kind: dataWarehouseNodeKind,
                id: entity.id,
                ...shared,
            })
        ) as any
    } else if (entity.type === EntityTypes.GROUPS) {
        return setLatestVersionsOnQuery(
            objectCleanWithEmpty({
                kind: NodeKind.GroupNode,
                ...shared,
            })
        ) as any
    }
    return setLatestVersionsOnQuery(
        objectCleanWithEmpty({
            kind: NodeKind.EventsNode,
            event: entity.id,
            ...shared,
        })
    ) as any
}

type FilterTypeActionsAndEventsWithGroups = FilterTypeActionsAndEvents & { groups: ActionFilter[] }
type FilterTypeActionsAndEventsWithoutGroups = Omit<FilterTypeActionsAndEvents, 'groups'> & { groups?: undefined }

export function actionsAndEventsToSeries(
    filters: FilterTypeActionsAndEventsWithGroups,
    includeProperties: boolean,
    includeMath: MathAvailability,
    dataWarehouseNodeKind?: NodeKind.DataWarehouseNode
): (AnyEntityNode | GroupNode)[]
export function actionsAndEventsToSeries(
    filters: FilterTypeActionsAndEventsWithoutGroups,
    includeProperties: boolean,
    includeMath: MathAvailability,
    dataWarehouseNodeKind: NodeKind.LifecycleDataWarehouseNode
): AnyEntityNode<LifecycleDataWarehouseNode>[]
export function actionsAndEventsToSeries(
    filters: FilterTypeActionsAndEventsWithoutGroups,
    includeProperties: boolean,
    includeMath: MathAvailability,
    dataWarehouseNodeKind: NodeKind.FunnelsDataWarehouseNode
): AnyEntityNode<FunnelsDataWarehouseNode>[]
export function actionsAndEventsToSeries(
    filters: FilterTypeActionsAndEventsWithoutGroups,
    includeProperties: boolean,
    includeMath: MathAvailability,
    dataWarehouseNodeKind?: NodeKind.DataWarehouseNode
): AnyEntityNode[]
export function actionsAndEventsToSeries(
    { actions, events, data_warehouse, new_entity, groups }: FilterTypeActionsAndEvents,
    includeProperties: boolean,
    includeMath: MathAvailability,
    dataWarehouseNodeKind: DataWarehouseNodeKind = NodeKind.DataWarehouseNode
): (AnyEntityNode<AnyDataWarehouseNode> | GroupNode<AnyDataWarehouseNode>)[] {
    const series: (AnyEntityNode<AnyDataWarehouseNode> | GroupNode<AnyDataWarehouseNode>)[] = [
        ...(actions || []),
        ...(events || []),
        ...(data_warehouse || []),
        ...(new_entity || []),
        ...(groups || []),
    ]
        .sort((a, b) => (a.order || b.order ? (!a.order ? -1 : !b.order ? 1 : a.order - b.order) : 0))
        .map((f) => legacyEntityToNode(f, includeProperties, includeMath, dataWarehouseNodeKind))

    return series
}

export const sanitizeRetentionEntity = (entity: RetentionEntity | undefined): RetentionEntity | undefined => {
    if (!entity) {
        return undefined
    }

    const { id, kind, name, type, order, uuid, custom_name } = entity
    return {
        ...('id' in entity ? { id } : {}),
        ...('kind' in entity ? { kind } : {}),
        ...('name' in entity ? { name } : {}),
        ...('type' in entity ? { type } : {}),
        ...('order' in entity ? { order } : {}),
        ...('uuid' in entity ? { uuid } : {}),
        ...('custom_name' in entity ? { custom_name } : {}),
    }
}

/** Expand GroupNodes into individual EventsNode/ActionsNode for insight types that don't support GroupNode */
export const expandGroupNodes = (
    series: (EventsNode | ActionsNode | DataWarehouseNode | GroupNode)[]
): (EventsNode | ActionsNode | DataWarehouseNode)[] => {
    return series.flatMap((item) =>
        item.kind === NodeKind.GroupNode ? (item.nodes as (EventsNode | ActionsNode | DataWarehouseNode)[]) : [item]
    )
}
