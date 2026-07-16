import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

// Kept in a leaf module (instead of universalFiltersLogic) so consumers that only need the default
// group don't import the logic's heavy dependency graph — the logic circularly imports back into
// scenes/session-recordings, which caused "Cannot access 'DEFAULT_UNIVERSAL_GROUP_FILTER' before
// initialization" TDZ errors on hot reload.
export const DEFAULT_UNIVERSAL_GROUP_FILTER: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [],
        },
    ],
}
