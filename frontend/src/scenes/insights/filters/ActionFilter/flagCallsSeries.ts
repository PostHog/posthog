import {
    DataWarehouseNode,
    FunnelsDataWarehouseNode,
    LifecycleDataWarehouseNode,
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
