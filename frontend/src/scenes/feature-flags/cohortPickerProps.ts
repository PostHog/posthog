import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyOperator } from '~/types'

/**
 * Picker props for surfaces where cohort filters are restricted to `in` only,
 * such as heatmap filters. Hides recents carrying any other cohort operator and
 * renders cohort rows as key-only (the cohort *is* the value, operator is implicit).
 *
 * Call sites using this preset:
 * - `products/web_analytics/frontend/heatmaps/components/FilterPanel.tsx`
 *
 * Feature flag release conditions deliberately do NOT use this preset: flag
 * matching supports `not_in` cohorts (see the Rust cohort-membership evaluation
 * in `rust/feature-flags/src/cohorts/cohort_operations.rs`), so the flag UI
 * shows the full `user in` / `user not in` operator dropdown. Workflow batch and
 * broadcast audiences don't use it either, because their audience query compiles
 * `not_in` to `NOT IN COHORT`.
 *
 * Spread into `PropertyFilters` / `TaxonomicPropertyFilter` rather than passing
 * each prop individually so the configuration travels as one named idea.
 */
export const COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS = {
    excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [PropertyOperator.NotIn] },
    selectingKeyOnly: { [TaxonomicFilterGroupType.Cohorts]: true },
}
