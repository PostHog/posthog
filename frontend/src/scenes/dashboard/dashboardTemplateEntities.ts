import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { objectCleanWithEmpty } from 'lib/utils/objects'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import {
    actorsOnlyMathTypes,
    calendarHeatmapMathTypes,
    funnelsMathTypes,
} from 'scenes/insights/filters/ActionFilter/cleanSeriesNodes'
import {
    SeriesNode,
    isActionsSeriesNode,
    isEventsSeriesNode,
    isWarehouseSeriesNode,
    seriesNodeEntityType,
    toActionId,
} from 'scenes/insights/filters/ActionFilter/seriesNode'

import { cleanEntityProperties } from '~/queries/nodes/InsightQuery/utils/cleanProperties'
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
    EntityTypes,
    FunnelDatawarehouseFilter,
    LifecycleDatawarehouseFilter,
    RetentionEntity,
    TemplateVariableStep,
    TrendsDataWarehouseFilter,
    isDataWarehouseFilter,
    isGroupFilter,
} from '~/types'

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

const STEP_IDENTITY_KEYS = ['type', 'id', 'order', 'index', 'uuid']
const NODE_IDENTITY_KEYS = ['kind', 'version', 'event', 'id', 'nodes']

/** When the picker holds more than one row, the first row of the earliest type here is the one stored. */
const TEMPLATE_STEP_TYPES = [EntityTypes.ACTIONS, EntityTypes.EVENTS, EntityTypes.DATA_WAREHOUSE]

function omitKeys(source: Record<string, any>, keys: string[]): Record<string, any> {
    return Object.fromEntries(Object.entries(source).filter(([key]) => !keys.includes(key)))
}

/**
 * The picker row for a template variable's default step. Only the identity keys translate. Every
 * other field, such as `math` or `custom_event`, keeps its name and copies through.
 */
export function templateVariableStepToSeries(step: TemplateVariableStep | undefined): SeriesNode[] {
    if (!step) {
        return []
    }
    const shared = omitKeys(step, STEP_IDENTITY_KEYS)
    if (Array.isArray(shared.properties)) {
        shared.properties = convertPropertyGroupToProperties(shared.properties)
    }

    if (step.type === EntityTypes.ACTIONS) {
        return [{ ...shared, kind: NodeKind.ActionsNode, id: toActionId(step.id) } as SeriesNode]
    }
    if (step.type === EntityTypes.DATA_WAREHOUSE) {
        // The table name is the node's key, and a step may carry it only as its `id`.
        const tableName = shared.table_name ?? (typeof step.id === 'string' ? step.id : undefined)
        return [
            {
                ...shared,
                kind: NodeKind.DataWarehouseNode,
                table_name: tableName,
                id: tableName ?? step.id,
            } as SeriesNode,
        ]
    }
    return [{ ...shared, kind: NodeKind.EventsNode, event: step.id } as SeriesNode]
}

export function seriesToTemplateVariableStep(series: SeriesNode[]): TemplateVariableStep | undefined {
    for (const type of TEMPLATE_STEP_TYPES) {
        const order = series.findIndex((node) => seriesNodeEntityType(node) === type)
        if (order >= 0) {
            return seriesNodeToTemplateVariableStep(series[order], order)
        }
    }
    return undefined
}

function seriesNodeToTemplateVariableStep(node: SeriesNode, order: number): TemplateVariableStep {
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
        id,
        type: seriesNodeEntityType(node),
        order,
    } as TemplateVariableStep
}
