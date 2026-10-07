import {
    DataWarehouseNode,
    FunnelsDataWarehouseNode,
    InsightQueryNode,
    LifecycleDataWarehouseNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

// Not a root table, so the `posthog.` prefix is part of the name. A team on the Events mode without
// the flag-evaluations-hogql-table flag has no such table. Queries on it fail to resolve for that team.
export const FLAG_EVALUATIONS_TABLE = 'posthog.flag_evaluations'

export const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'

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
