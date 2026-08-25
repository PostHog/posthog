import type { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

// Kept in a leaf module (instead of universalFiltersLogic) so consumers that only need the default
// group don't import the logic's heavy dependency graph — the logic circularly imports back into
// scenes/session-recordings, which caused "Cannot access 'DEFAULT_UNIVERSAL_GROUP_FILTER' before
// initialization" TDZ errors on hot reload.
// String literal, not FilterLogicalOperator.And: a value import of ~/types here would recreate the circular import this leaf module exists to avoid.
// constants.test.ts asserts this equals FilterLogicalOperator.And, so drift between the literal and the enum fails loudly.
// A no-restricted-imports override in .oxlintrc.json blocks a value import of ~/types in this file specifically:
// the transitive cycle is ~80 hops deep, far past import/no-cycle's configured maxDepth, so that rule can't catch a regression here.
const AND = 'AND' as FilterLogicalOperator

export const DEFAULT_UNIVERSAL_GROUP_FILTER: UniversalFiltersGroup = {
    type: AND,
    values: [
        {
            type: AND,
            values: [],
        },
    ],
}
