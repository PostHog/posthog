import { FEATURE_FLAG_CALLED_EVENT, FLAG_EVALUATIONS_TABLE } from 'scenes/feature-flags/flagEvaluationsTable'

import {
    DataWarehouseNode,
    FunnelsDataWarehouseNode,
    InsightQueryNode,
    LifecycleDataWarehouseNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { AnyPropertyFilter, DataWarehousePropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

export const FLAG_CALLS_SERIES_NAME: string = CORE_FILTER_DEFINITIONS_BY_GROUP.events[FEATURE_FLAG_CALLED_EVENT].label

/** A picker keeps only the fields its own warehouse series kind takes. */
export const FLAG_EVALUATIONS_SERIES_FIELDS: Required<
    Pick<DataWarehouseNode, 'id_field' | 'timestamp_field' | 'distinct_id_field'> &
        Pick<FunnelsDataWarehouseNode, 'aggregation_target_field'> &
        Pick<LifecycleDataWarehouseNode, 'created_at_field'>
> = {
    id_field: 'uuid',
    timestamp_field: 'timestamp',
    distinct_id_field: 'distinct_id',
    // person_id is the merge-corrected person. A flag calls step counts the same person as an events step.
    aggregation_target_field: 'person_id',
    // The table stores no person creation time. Lifecycle takes the earliest flag call it reads instead.
    created_at_field: 'timestamp',
}

export function readsFlagCalls(query: InsightQueryNode): boolean {
    const nodes: unknown[] =
        query.kind === NodeKind.RetentionQuery
            ? [query.retentionFilter?.targetEntity, query.retentionFilter?.returningEntity]
            : 'series' in query
              ? (query.series ?? [])
              : []
    return nodes.some((node) => (node as { table_name?: string } | undefined)?.table_name === FLAG_EVALUATIONS_TABLE)
}

/** Sets the actor column of each flag calls series to the query's aggregation: a group key, or the person. */
export function withFlagCallsAggregationTarget<Q extends InsightQueryNode>(query: Q): Q {
    const groupTypeIndex = 'aggregation_group_type_index' in query ? query.aggregation_group_type_index : null
    const target =
        groupTypeIndex != null ? `$group_${groupTypeIndex}` : FLAG_EVALUATIONS_SERIES_FIELDS.aggregation_target_field
    const retarget = <T>(node: T): T => {
        const fields = node as { table_name?: string; aggregation_target_field?: string } | null | undefined
        return fields?.table_name === FLAG_EVALUATIONS_TABLE &&
            fields.aggregation_target_field != null &&
            fields.aggregation_target_field !== target
            ? { ...node, aggregation_target_field: target }
            : node
    }

    if (query.kind === NodeKind.RetentionQuery) {
        const { targetEntity, returningEntity } = query.retentionFilter ?? {}
        const nextTarget = retarget(targetEntity)
        const nextReturning = retarget(returningEntity)
        return nextTarget === targetEntity && nextReturning === returningEntity
            ? query
            : {
                  ...query,
                  retentionFilter: {
                      ...query.retentionFilter,
                      targetEntity: nextTarget,
                      returningEntity: nextReturning,
                  },
              }
    }
    if ('series' in query && query.series) {
        const series = query.series.map(retarget)
        return series.some((node, index) => node !== query.series[index]) ? { ...query, series } : query
    }
    return query
}

const FLAG_CALLS_COLUMN_BY_EVENT_PROPERTY: Record<string, string> = {
    $feature_flag: 'flag_key',
    $feature_flag_response: 'response',
}

/** Rewrites an event series' flag filters onto the flag_evaluations columns and keeps its SQL filters. */
export function flagCallsFiltersFromEventFilters(properties: AnyPropertyFilter[] | undefined): AnyPropertyFilter[] {
    return (properties ?? []).flatMap((property): AnyPropertyFilter[] => {
        if (property.type === PropertyFilterType.HogQL) {
            return [property]
        }
        if (property.type !== PropertyFilterType.Event) {
            return []
        }
        const column = FLAG_CALLS_COLUMN_BY_EVENT_PROPERTY[property.key]
        // An event read turns a missing response into NULL. The table stores it as '' or 'null', so set checks differ.
        if (
            !column ||
            property.operator === PropertyOperator.IsSet ||
            property.operator === PropertyOperator.IsNotSet
        ) {
            return []
        }
        const filter: DataWarehousePropertyFilter = {
            key: column,
            value: property.value,
            operator: property.operator,
            type: PropertyFilterType.DataWarehouse,
        }
        return [filter]
    })
}
