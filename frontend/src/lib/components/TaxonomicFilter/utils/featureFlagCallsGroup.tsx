import { IconFlag } from '@posthog/icons'

import { SimpleOption, TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { hiddenEventNames, hiddenEventSearchTerms } from 'lib/components/TaxonomicFilter/utils/hiddenEvents'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import {
    DataWarehouseNode,
    FunnelsDataWarehouseNode,
    LifecycleDataWarehouseNode,
} from '~/queries/schema/schema-general'

// Not a root table, so the `posthog.` prefix is part of the name. A team on the Events mode without
// the flag-evaluations-hogql-table flag has no such table. Queries on it fail to resolve for that team.
export const FLAG_EVALUATIONS_TABLE = 'posthog.flag_evaluations'

/**
 * The columns a flag calls series reads, for every data warehouse series kind. A picker keeps only
 * the fields its own series kind takes.
 */
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

export const FEATURE_FLAG_CALLS_LABEL = 'Feature flag calls'

const SEARCH_TERMS = [FEATURE_FLAG_CALLS_LABEL.toLowerCase(), ...hiddenEventSearchTerms('$feature_flag_called')]

/**
 * Returns the "Feature flag calls" group, or nothing when the picker does not hide `$feature_flag_called`.
 * The entry charts the same calls as that event, read from `posthog.flag_evaluations`.
 */
export function featureFlagCallsGroups(
    flagEvaluationsMode: FlagEvaluationsModeEnumApi | undefined,
    includeHiddenEvents?: boolean
): TaxonomicFilterGroup[] {
    if (!hiddenEventNames(flagEvaluationsMode, includeHiddenEvents).includes('$feature_flag_called')) {
        return []
    }
    return [
        {
            name: FEATURE_FLAG_CALLS_LABEL,
            searchPlaceholder: 'feature flag calls',
            type: TaxonomicFilterGroupType.FeatureFlagCalls,
            options: [
                { name: FEATURE_FLAG_CALLS_LABEL, description: 'The same data as the Feature flag called event.' },
            ],
            localItemsSearch: (items, query) => {
                const normalized = query.trim().toLowerCase()
                return !normalized || SEARCH_TERMS.some((term) => term.includes(normalized)) ? items : []
            },
            getName: (option: SimpleOption) => option.name,
            getValue: (option: SimpleOption) => option.name,
            getPopoverHeader: () => FEATURE_FLAG_CALLS_LABEL,
            getIcon: () => <IconFlag />,
        },
    ]
}
